#! /usr/bin/python
# -*- coding: utf-8 -*-

import argparse

import torch

from ..hparams import get_hparams
from ..utils.search_space import LSTMSpaces, ConvolutionalSpaces, AttentionSpaces
from ..optimizers import AllOptimizers
from ..optimizers.lr_schedulers import AllLRSchedulers
from ..criterions import AllCriterions

__author__ = 'fyabc'


def add_general_args(parser):
    group = parser.add_argument_group('General Options', description='General options.')
    group.add_argument('--log-level', dest='logging_level', type=str, default='INFO', metavar='LEVEL',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='logging level, default is %(default)s')
    group.add_argument('--no-progress-bar', action='store_true', help='disable progress bar')
    group.add_argument('--log-interval', type=int, default=1000, metavar='N',
                       help='log progress every N batches (when progress bar is disabled)')
    group.add_argument('--log-format', default=None, help='log format to use',
                       choices=['json', 'none', 'simple', 'tqdm'])
    group.add_argument('-H', '--hparams-set', dest='hparams_set', type=str, default='base')
    group.add_argument('-T', '--task', dest='task', type=str, default='test')
    group.add_argument('--seed', dest='seed', type=int, default=1, metavar='N',
                       help='pseudo random number generator seed')
    group.add_argument('-N', '--net-code-file', dest='net_code_file', type=str, metavar='FILE',
                       default='net_code_example/default.json', help='net code filename')
    group.add_argument('--batch-first', action='store_false', dest='time_first',
                       help='Enable batch first mode, default is time first mode')
    group.add_argument('--time-first', action='store_true', default=True,
                       help='Enable time first mode, default is %(default)r')
    return group


def add_hparams_args(parser):
    # [NOTE]: HParams options must have default value of None, that can be overridden by hparams set.
    group = parser.add_argument_group('HParams Options', description='Options that set hyper-parameters.')
    group.add_argument('--max-src-positions', type=int, default=None, metavar='N',
                       help='max number of tokens in the source sequence')
    group.add_argument('--max-trg-positions', type=int, default=None, metavar='N',
                       help='max number of tokens in the target sequence')
    group.add_argument('--src-emb-size', dest='src_embedding_size', type=int, default=None)
    group.add_argument('--trg-emb-size', dest='trg_embedding_size', type=int, default=None)
    group.add_argument('--decoder-out-embed-size', dest='decoder_out_embedding_size', type=int, metavar='N',
                       default=None, help='decoder output embedding dimension')
    group.add_argument('--share-input-output-embed', dest='share_input_output_embedding', action='store_true',
                       default=None, help='share input and output embeddings (requires --decoder-out-embed-size'
                                          ' and --trg-emb-size to be equal)')
    group.add_argument('--no-share-input-output-embed', dest='share_input_output_embedding', action='store_false',
                       default=None, help='Do not share input and output embeddings (see --share-src-trg-embed)')
    group.add_argument('--share-src-trg-embed', dest='share_src_trg_embedding', action='store_true',
                       default=None, help='share source and target embeddings (requires source and target vocabulary '
                                          'size to be equal and --src-emb-size and --trg-emb-size to be equal)')
    group.add_argument('--no-share-src-trg-embed', dest='share_src_trg_embedding', action='store_false',
                       default=None, help='Do not share source and target embeddings (see --share-src-trg-embed)')
    group.add_argument('--dropout', type=float, default=None, metavar='D',
                       help='dropout value')
    group.add_argument('--lstm-space', dest='lstm_space', type=str, default=None,
                       choices=LSTMSpaces.keys(),
                       help='LSTM search space: {}'.format(', '.join(LSTMSpaces.keys())))
    group.add_argument('--conv-space', dest='conv_space', type=str, default=None,
                       choices=ConvolutionalSpaces.keys(),
                       help='Convolutional search space: {}'.format(', '.join(ConvolutionalSpaces.keys())))
    group.add_argument('--attn-space', dest='attn_space', type=str, default=None,
                       choices=AttentionSpaces.keys(),
                       help='Attention search space: {}'.format(', '.join(AttentionSpaces.keys())))

    # About initializer.
    group.add_argument('--initializer', type=str, default=None,
                       help='Initializer type')

    # About training.
    group.add_argument('--lr', '--learning-rate', default=None, metavar='LR_1,LR_2,...,LR_N',
                       help='learning rate for the first N epochs; all epochs >N using LR_N'
                            ' (note: this may be interpreted differently depending on --lr-scheduler)')
    group.add_argument('--momentum', default=None, type=float, metavar='M',
                       help='momentum factor')
    group.add_argument('--weight-decay', '--wd', default=None, type=float, metavar='WD',
                       help='weight decay')
    group.add_argument('--clip-norm', default=None, type=float, metavar='NORM',
                       help='clip threshold of gradients')


def add_extra_options_args(parser):
    group = parser.add_argument_group('Extra Options:')

    # Arbitrary extra options.
    group.add_argument('--extra-options', default="", type=str, metavar='OPT_STR',
                       help=r'String to represent extra options, format: comma-separated list of `name=value`. '
                            r'Use "@" instead of double-quotes.')

    return group


def add_dataset_args(parser, train=False, gen=False):
    group = parser.add_argument_group('Dataset Options:')
    group.add_argument('--data-dir', default=None, type=str, metavar='DIR',
                       help='Data save directory, default is "$PROJECT/data/"')
    group.add_argument('-b', '--max-sentences', '--batch-size', dest='max_sentences', type=int, metavar='N',
                       help='maximum number of sentences in a batch')
    group.add_argument('--max-tokens', default=6000, type=int, metavar='N',
                       help='maximum number of tokens in a batch')
    group.add_argument('--skip-invalid-size-inputs-valid-test', action='store_true',
                       help='Ignore too long or too short lines in valid and test set')
    if train:
        group.add_argument('--train-subset', default='train', metavar='SPLIT',
                           choices=['train', 'dev', 'test'],
                           help='data subset to use for training (train, dev, test)')
        group.add_argument('--valid-subset', default='dev', metavar='SPLIT',
                           help='comma separated list of data subsets to use for validation'
                                ' (train, dev, dev1, test, test1)')
        group.add_argument('--max-sentences-valid', type=int, metavar='N',
                           help='maximum number of sentences in a validation batch'
                                ' (defaults to --max-sentences)')
    if gen:
        group.add_argument('--gen-subset', default='test', metavar='SPLIT',
                           help='data subset to generate (train, valid, test)')
        group.add_argument('--num-shards', default=1, type=int, metavar='N',
                           help='shard generation over N shards')
        group.add_argument('--shard-id', default=0, type=int, metavar='ID',
                           help='id of the shard to generate (id < num_shards)')
    return group


def add_train_args(parser):
    group = parser.add_argument_group('Training Options', description='Options in training process.')
    group.add_argument('--criterion', default='cross_entropy', metavar='CRIT',
                       choices=AllCriterions.keys(),
                       help='training criterion: {} (default: %(default)s)'.format(
                           ', '.join(AllCriterions.keys())))
    for criterion in AllCriterions.values():
        criterion.add_args(group)
    group.add_argument('--max-epoch', '--me', default=0, type=int, metavar='N',
                       help='force stop training at specified epoch, default is inf')
    group.add_argument('--max-update', '--mu', default=0, type=int, metavar='N',
                       help='force stop training at specified update, default is inf')
    group.add_argument('--sentence-avg', action='store_true', default=False,
                       help='normalize gradients by the number of sentences in a batch'
                            ' (default is to normalize by number of tokens)')
    group.add_argument('--update-freq', default='1', metavar='N',
                       help='update parameters every N_i batches, when in epoch i')
    group.add_argument('--optimizer', default='nag', metavar='OPT',
                       choices=AllOptimizers.keys(),
                       help='optimizer: {} (default: %(default)s)'.format(', '.join(AllOptimizers.keys())))
    for optimizer in AllOptimizers.values():
        optimizer.add_args(group)

    group.add_argument('--lr-scheduler', default='reduce_lr_on_plateau',
                       help='learning rate scheduler: {} (default: reduce_lr_on_plateau)'.format(
                           ', '.join(AllLRSchedulers.keys())))
    for lr_scheduler in AllLRSchedulers.values():
        lr_scheduler.add_args(group)
    group.add_argument('--lr-shrink', default=0.1, type=float, metavar='LS',
                       help='learning rate shrink factor for annealing, lr_new = (lr * lr_shrink)')
    group.add_argument('--min-lr', default=1e-5, type=float, metavar='LR',
                       help='minimum learning rate')

    group.add_argument('--sample-without-replacement', default=0, type=int, metavar='N',
                       help='If bigger than 0, use that number of mini-batches for each epoch,'
                            ' where each sample is drawn randomly without replacement from the'
                            ' dataset')
    group.add_argument('--curriculum', default=0, type=int, metavar='N',
                       help='sort batches by source length for first N epochs')
    return group


def add_distributed_args(parser):
    # TODO: Use `DataParallel` now, clean and refactor arguments and other related code.
    # Move these options into DataParallel.

    group = parser.add_argument_group(
        'Distributed Options', description='Options that set distributed training.')
    group.add_argument('--distributed-world-size', type=int, metavar='N',
                       default=torch.cuda.device_count(),
                       help='total number of GPUs across all nodes (default: all visible GPUs)')
    group.add_argument('--distributed-rank', default=0, type=int,
                       help='rank of the current worker')
    group.add_argument('--distributed-backend', default='nccl', type=str,
                       help='distributed backend')
    group.add_argument('--distributed-init-method', default=None, type=str,
                       help='typically tcp://hostname:port that will be used to '
                            'establish initial connection')
    group.add_argument('--distributed-port', default=-1, type=int,
                       help='port number (not required if using --distributed-init-method)')
    group.add_argument('--device-id', type=int, default=0, metavar='N',
                       help='GPU device id, usually automatically set')
    return group


def add_checkpoint_args(parser, gen=False):
    group = parser.add_argument_group('Checkpoint Options')
    group.add_argument('--model-dir', default=None, type=str, metavar='DIR',
                       help='Model save directory, default is "$PROJECT/models/"')
    group.add_argument('--restore-file', default='checkpoint_last.pt',
                       help='Filename in model directory from which to load checkpoint, '
                            'default is %(default)s')
    group.add_argument('--exp-dir', default=None,
                       help='The additional experiment directory, default is %(default)s')
    if not gen:
        group.add_argument('--save-interval', type=int, default=-1, metavar='N',
                           help='save a checkpoint every N updates')
        group.add_argument('--no-save', action='store_true', default=False,
                           help='don\'t save models and checkpoints')
        group.add_argument('--no-epoch-checkpoints', action='store_true',
                           help='only store last and best checkpoints')
        group.add_argument('--validate-interval', type=int, default=1, metavar='N',
                           help='validate every N epochs')
    return group


def add_generation_args(parser):
    group = parser.add_argument_group('Generation Options')

    group.add_argument('--path', metavar='FILE', action='append',
                       help='path(s) to model file(s)')
    group.add_argument('--greedy-sample-temp', default=0.0, type=float, metavar='N', dest='greedy_sample_temperature',
                       help='greedy sample temperature, default is %(default)s')
    group.add_argument('--beam', default=5, type=int, metavar='N',
                       help='beam size')
    group.add_argument('--nbest', default=1, type=int, metavar='N',
                       help='number of hypotheses to output')
    group.add_argument('--max-len-a', default=0, type=float, metavar='N', dest='maxlen_a',
                       help=('generate sequences of maximum length ax + b, '
                             'where x is the source length'))
    group.add_argument('--max-len-b', default=200, type=int, metavar='N', dest='maxlen_b',
                       help=('generate sequences of maximum length ax + b, '
                             'where x is the source length'))
    # TODO: This option need test
    group.add_argument('--use-task-maxlen', default=False, action='store_true',
                       help='use maxlen information in the task')
    group.add_argument('--no-early-stop', action='store_true',
                       help=('continue searching even after finalizing k=beam '
                             'hypotheses; this is more correct, but increases '
                             'generation time by 50%%'))
    group.add_argument('--unnormalized', action='store_true',
                       help='compare unnormalized hypothesis scores')
    group.add_argument('--cpu', action='store_true', help='generate on CPU')
    group.add_argument('--no-beamable-mm', action='store_true',
                       help='don\'t use BeamableMM in attention layers')
    group.add_argument('--lenpen', default=1, type=float,
                       help='length penalty: <1.0 favors shorter, >1.0 favors longer sentences')
    group.add_argument('--unkpen', default=0, type=float,
                       help='unknown word penalty: <0 produces more unks, >0 produces fewer')
    group.add_argument('--replace-unk', nargs='?', const=True, default=None,
                       help='perform unknown replacement (optionally with alignment dictionary)')
    group.add_argument('--quiet', action='store_true',
                       help='only print final scores')
    group.add_argument('--score-reference', action='store_true',
                       help='just score the reference translation')
    group.add_argument('--prefix-size', default=0, type=int, metavar='PS',
                       help='initialize generation by target prefix of given length')
    group.add_argument('--sampling', action='store_true',
                       help='sample hypotheses instead of using beam search')
    group.add_argument('--output-dir', default=None, type=str, metavar='DIR',
                       help='Translation output directory, default is "$PROJECT/translated/"')
    group.add_argument('--output-file', default=None, type=str, metavar='FILE',
                       help='Translation output filename, default is None (does not output)')
    group.add_argument('--model-overrides', default="{}", type=str, metavar='DICT',
                       help='a dictionary used to override model args at generation that were used during model '
                            'training')
    return group


def parse_extra_options(parsed_args):
    _extra_dict = eval('dict({})'.format(parsed_args.extra_options.replace('@', '"')))
    for name, value in _extra_dict.items():
        setattr(parsed_args, name, value)

    return parsed_args


def get_args(args=None):
    parser = argparse.ArgumentParser(description='Training Script.')

    add_general_args(parser)
    add_hparams_args(parser)
    add_extra_options_args(parser)
    add_dataset_args(parser, train=True)
    add_train_args(parser)
    add_distributed_args(parser)
    add_checkpoint_args(parser)

    parsed_args = parser.parse_args(args)

    parse_extra_options(parsed_args)

    return parsed_args


def get_generator_args(args=None):
    parser = argparse.ArgumentParser(description='Generating Script.')

    add_general_args(parser)
    add_extra_options_args(parser)
    add_checkpoint_args(parser, gen=True)
    add_dataset_args(parser, gen=True)
    add_generation_args(parser)
    # TODO: Add other args.

    parsed_args = parser.parse_args(args)

    parse_extra_options(parsed_args)

    return parsed_args
