#! /usr/bin/python
# -*- coding: utf-8 -*-

import logging
import math
import os

import torch as th

from .utils.main_utils import main_entry
from .utils.paths import get_model_path, get_translate_output_path
from .utils.data_processing import ShardedIterator
from .utils.meters import StopwatchMeter
from .utils import common
from .tasks import get_task

__author__ = 'fyabc'


class ChildGenerator:
    def __init__(self, hparams, datasets, models, maxlen=None):
        """

        Args:
            hparams: HParams object.
            datasets:
            models (list): List (ensemble) of models.
        """
        self.hparams = hparams
        self.datasets = datasets
        self.task = get_task(hparams.task)
        self.models = models
        self.is_cuda = False

        max_decoder_len = min(m.max_decoder_positions() for m in self.models)
        max_decoder_len -= 1  # we define maxlen not including the EOS marker
        self.maxlen = max_decoder_len if maxlen is None else min(maxlen, max_decoder_len)

    def _get_input_iter(self):
        itr = self.datasets.eval_dataloader(
            self.hparams.gen_subset,
            max_sentences=self.hparams.max_sentences,
            max_positions=min(model.max_encoder_positions() for model in self.models),
            skip_invalid_size_inputs_valid_test=self.hparams.skip_invalid_size_inputs_valid_test,
        )

        if self.hparams.num_shards > 1:
            if not (0 <= self.hparams.shard_id < self.hparams.num_shards):
                raise ValueError('--shard-id must be between 0 and num_shards')
            itr = ShardedIterator(itr, self.hparams.num_shards, self.hparams.shard_id)

        return itr

    def cuda(self):
        for model in self.models:
            model.cuda()
        self.is_cuda = True
        return self

    def greedy_decoding(self):
        return self.decoding(beam=None)

    def beam_search(self):
        return self.decoding(beam=self.hparams.beam)

    def decoding(self, beam=None):
        itr = self._get_input_iter()

        gen_timer = StopwatchMeter()

        src_dict, trg_dict = self.datasets.source_dict, self.datasets.target_dict

        gen_subset_len = len(self.datasets.get_dataset(self.hparams.gen_subset))

        translated_strings = [None for _ in range(gen_subset_len)]
        for i, sample in enumerate(itr):
            if beam is None or beam <= 1:
                batch_translated_tokens = self._greedy_decoding(sample, gen_timer)
            else:
                batch_translated_tokens = self._beam_search_slow(sample, beam, gen_timer)
            print('Batch {}:'.format(i))
            for id_, src_tokens, trg_tokens, translated_tokens in zip(
                    sample['id'], sample['net_input']['src_tokens'], sample['target'], batch_translated_tokens):
                print('SOURCE:', src_dict.string(src_tokens, bpe_symbol=self.task.BPESymbol))
                print('REF   :', trg_dict.string(trg_tokens, bpe_symbol=self.task.BPESymbol, escape_unk=True))
                trans_str = trg_dict.string(translated_tokens, bpe_symbol=self.task.BPESymbol, escape_unk=True)
                print('DECODE:', trans_str)
                translated_strings[id_] = trans_str
            print()

        logging.info('Translated {} sentences in {:.1f}s ({:.2f} sentences/s)'.format(
            gen_timer.n, gen_timer.sum, 1. / gen_timer.avg))

        # Dump decoding outputs.
        if self.hparams.output_file is not None:
            output_path = get_translate_output_path(self.hparams)
            os.makedirs(output_path, exist_ok=True)
            full_path = os.path.join(output_path, self.hparams.output_file)
            with open(full_path, 'w') as f:
                for line in translated_strings:
                    assert line is not None, 'There is a sentence not being translated'
                    print(line, file=f)
            logging.info('Decode output write to {}.'.format(full_path))

    def _get_maxlen(self, srclen):
        if self.hparams.use_task_maxlen:
            a, b = self.task.get_maxlen_a_b()
        else:
            a, b = self.hparams.maxlen_a, self.hparams.maxlen_b
        maxlen = max(1, int(a * srclen + b))
        return maxlen

    def _greedy_decoding(self, sample, timer=None):
        """

        Args:
            sample (dict):
            timer (StopwatchMeter):
        """

        sample = common.make_variable(sample, volatile=True, cuda=self.is_cuda)
        batch_size = sample['id'].numel()
        input_ = sample['net_input']
        srclen = input_['src_tokens'].size(1)
        start_symbol = self.task.EOS_ID

        maxlen = self._get_maxlen(srclen)

        for model in self.models:
            model.eval()

        if timer is not None:
            timer.start()

        with common.maybe_no_grad():
            encoder_outs = [
                model.encode(input_['src_tokens'], input_['src_lengths'])
                for model in self.models
            ]

            trg_tokens = common.make_variable(
                th.zeros(batch_size, 1).fill_(start_symbol).type_as(input_['src_tokens'].data),
                volatile=True, cuda=self.is_cuda)
            trg_lengths = common.make_variable(
                th.zeros(batch_size).fill_(1).type_as(input_['src_lengths'].data),
                volatile=True, cuda=self.is_cuda)
            for i in range(maxlen - 1):
                net_outputs = [
                    model.decode(
                        encoder_out, input_['src_lengths'],
                        trg_tokens, trg_lengths)
                    for encoder_out, model in zip(encoder_outs, self.models)
                ]

                avg_probs, _ = self._get_normalized_probs(net_outputs)

                if self.hparams.greedy_sample_temperature == 0.0:
                    _, next_word = avg_probs.max(dim=1)
                else:
                    assert self.hparams.greedy_sample_temperature > 0.0
                    next_word = th.multinomial(th.exp(avg_probs) / self.hparams.greedy_sample_temperature, 1)[:, 0]

                trg_tokens.data = th.cat([trg_tokens.data, th.unsqueeze(next_word, dim=1)], dim=1)
                trg_lengths += 1

        if timer is not None:
            timer.stop(batch_size)

        # Remove start tokens.
        return trg_tokens[:, 1:].data

    def _beam_search_slow(self, sample, beam, timer=None):
        sample = common.make_variable(sample, volatile=True, cuda=self.is_cuda)
        batch_size = sample['id'].numel()
        input_ = sample['net_input']
        src_tokens = input_['src_tokens']
        srclen = src_tokens.size(1)
        start_symbol = self.task.EOS_ID

        maxlen = self._get_maxlen(srclen)

        for model in self.models:
            model.eval()

        if timer is not None:
            timer.start()

        with common.maybe_no_grad():
            encoder_outs = [
                model.encode(input_['src_tokens'], input_['src_lengths'])
                for model in self.models
            ]

            # buffers
            scores = src_tokens.data.new(batch_size * beam, maxlen + 1).float().fill_(0)
            scores_buf = scores.clone()
            tokens = src_tokens.data.new(batch_size * beam, maxlen + 2).fill_(self.task.PAD_ID)
            tokens_buf = tokens.clone()
            tokens[:, 0] = start_symbol
            attn = scores.new(batch_size * beam, src_tokens.size(1), maxlen + 2)
            attn_buf = attn.clone()

            # list of completed sentences
            finalized = [[] for i in range(batch_size)]
            finished = [False for i in range(batch_size)]
            worst_finalized = [{'idx': None, 'score': -math.inf} for i in range(batch_size)]
            num_remaining_sent = batch_size

            # number of candidate hypos per step
            cand_size = 2 * beam    # 2 x beam size in case half are EOS

            # offset arrays for converting between different indexing schemes
            bbsz_offsets = (th.arange(0, batch_size) * beam).unsqueeze(1).type_as(tokens)
            cand_offsets = th.arange(0, cand_size).type_as(tokens)

            # helper function for allocating buffers on the fly
            buffers = {}

            def buffer(name, type_of=tokens):
                if name not in buffers:
                    buffers[name] = type_of.new()
                return buffers[name]

            # TODO

        if timer is not None:
            timer.stop(batch_size)

        # TODO: Just for test now
        return sample['target'].data

    def _get_normalized_probs(self, net_outputs, compute_attn=False):
        avg_probs = None
        avg_attn = None
        for model, (output, attn) in zip(self.models, net_outputs):
            output = output[:, -1, :]
            probs = model.get_normalized_probs((output, avg_attn), log_probs=False).data
            if avg_probs is None:
                avg_probs = probs
            else:
                avg_probs.add_(probs)

            if not compute_attn:
                continue
            if attn is not None:
                if self.hparams.enc_dec_attn_type == 'fairseq':
                    attn = attn[:, -1, :].data
                elif self.hparams.enc_dec_attn_type == 'dot_product':
                    attn = attn[:, :, -1, :].data
                else:
                    raise ValueError('Unknown encoder-decoder attention type {}'.format(self.hparams.enc_dec_attn_type))
                if avg_attn is None:
                    avg_attn = attn
                else:
                    avg_attn.add_(attn)
        avg_probs.div_(len(self.models))
        avg_probs.log_()

        if compute_attn and avg_attn is not None:
            avg_attn.div_(len(self.models))
        return avg_probs, avg_attn


def generate_main(hparams, datasets=None):
    components = main_entry(hparams, datasets, train=False)

    # Check generator hparams
    assert hparams.path is not None, '--path required for generation!'
    assert not hparams.sampling or hparams.nbest == hparams.beam, '--sampling requires --nbest to be equal to --beam'

    net_code = components['net_code']
    datasets = components['datasets']

    use_cuda = th.cuda.is_available() and not hparams.cpu

    # Load ensemble
    model_path = get_model_path(hparams)
    logging.info('Loading models from {}'.format(', '.join(hparams.path)))
    models, _ = common.load_ensemble_for_inference(
        [os.path.join(model_path, name) for name in hparams.path], net_code=net_code)

    # TODO: Optimize ensemble for generation
    # TODO: Load alignment dictionary for unknown word replacement

    # Build generator
    generator = ChildGenerator(hparams, datasets, models)
    if use_cuda:
        generator.cuda()
        logging.info('Use CUDA, running on device {}'.format(th.cuda.current_device()))

    if hparams.beam <= 0:
        generator.greedy_decoding()
    else:
        generator.beam_search()
