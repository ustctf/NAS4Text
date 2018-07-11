#! /usr/bin/python
# -*- coding: utf-8 -*-

import torch.nn as nn
import torch.nn.functional as F

from ..tasks import get_task
from ..layers.common import *
from ..utils import common
from ..utils.data_processing import LanguagePairDataset

__author__ = 'fyabc'


class ChildNetBase(nn.Module):
    _Subclasses = {}

    def __init__(self, net_code, hparams):
        super().__init__()
        self.net_code = net_code
        self.hparams = hparams

    @classmethod
    def register_child_net(cls, subclass):
        cls._Subclasses[subclass.__name__] = subclass
        return subclass

    @classmethod
    def get_net(cls, net_type):
        return cls._Subclasses[net_type]

    def forward(self, *args):
        raise NotImplementedError()

    def encode(self, src_tokens, src_lengths):
        raise NotImplementedError()

    def decode(self, encoder_out, src_lengths, trg_tokens, trg_lengths):
        raise NotImplementedError()

    def get_normalized_probs(self, net_output, log_probs=False):
        raise NotImplementedError()

    def get_targets(self, sample, net_output):
        """Get targets from either the sample or the net's output."""
        return sample['target']

    def max_encoder_positions(self):
        raise NotImplementedError()

    def max_decoder_positions(self):
        raise NotImplementedError()

    def load_state_dict(self, state_dict, strict=True):
        """Copies parameters and buffers from state_dict into this module and
        its descendants.

        Overrides the method in nn.Module; compared with that method this
        additionally "upgrades" state_dicts from old checkpoints.
        """
        state_dict = self.upgrade_state_dict(state_dict)
        super().load_state_dict(state_dict, strict)

    def upgrade_state_dict(self, state_dict):
        raise NotImplementedError()

    def num_parameters(self):
        """Number of parameters."""
        return sum(p.data.numel() for p in self.parameters())


class EncDecChildNet(ChildNetBase):
    def __init__(self, net_code, hparams):
        super().__init__(net_code, hparams)
        self.encoder = None
        self.decoder = None

    def forward(self, src_tokens, src_lengths, trg_tokens, trg_lengths):
        """

        Args:
            src_tokens: (batch_size, src_seq_len) of int32
            src_lengths: (batch_size,) of long
            trg_tokens: (batch_size, trg_seq_len) of int32
            trg_lengths: (batch_size,) of long

        Returns:
            (batch_size, seq_len, tgt_vocab_size) of float32
        """
        encoder_out = self.encoder(src_tokens, src_lengths)
        decoder_out = self.decoder(encoder_out, src_lengths, trg_tokens, trg_lengths)

        return decoder_out

    def encode(self, src_tokens, src_lengths):
        return self.encoder(src_tokens, src_lengths)

    def decode(self, encoder_out, src_lengths, trg_tokens, trg_lengths):
        return self.decoder(encoder_out, src_lengths, trg_tokens, trg_lengths)

    def get_normalized_probs(self, net_output, log_probs=False):
        return self.decoder.get_normalized_probs(net_output, log_probs)

    def max_encoder_positions(self):
        return self.encoder.max_positions()

    def max_decoder_positions(self):
        return self.decoder.max_positions()

    def upgrade_state_dict(self, state_dict):
        state_dict = self.encoder.upgrade_state_dict(state_dict)
        state_dict = self.decoder.upgrade_state_dict(state_dict)
        return state_dict


class ChildDecoderBase(nn.Module):
    def __init__(self, code, hparams, **kwargs):
        super().__init__()

        self.code = code
        self.hparams = hparams
        self.task = get_task(hparams.task)

        self.embed_tokens = None
        self.embed_position = None
        self.fc_last = None

    def _build_embedding(self, src_embedding=None):
        hparams = self.hparams

        if hparams.share_src_trg_embedding:
            assert self.task.SourceVocabSize == self.task.TargetVocabSize, \
                'Shared source and target embedding weights implies same source and target vocabulary size, but got ' \
                '{}(src) vs {}(trg)'.format(self.task.SourceVocabSize, self.task.TargetVocabSize)
            assert hparams.src_embedding_size == hparams.trg_embedding_size, \
                'Shared source and target embedding weights implies same source and target embedding size, but got ' \
                '{}(src) vs {}(trg)'.format(hparams.src_embedding_size, hparams.trg_embedding_size)
            self.embed_tokens = nn.Embedding(
                self.task.TargetVocabSize, hparams.trg_embedding_size, padding_idx=self.task.PAD_ID)
            self.embed_tokens.weight = src_embedding.weight
        else:
            self.embed_tokens = Embedding(self.task.TargetVocabSize, hparams.trg_embedding_size, self.task.PAD_ID,
                                          hparams=hparams)
        self.embed_positions = PositionalEmbedding(
            hparams.max_trg_positions,
            hparams.trg_embedding_size,
            self.task.PAD_ID,
            left_pad=LanguagePairDataset.LEFT_PAD_TARGET,
            hparams=hparams,
        )

    def _build_fc_last(self):
        hparams = self.hparams

        if hparams.share_input_output_embedding:
            assert hparams.trg_embedding_size == hparams.decoder_out_embedding_size, \
                'Shared embed weights implies same dimensions out_embedding_size={} vs trg_embedding_size={}'.format(
                    hparams.decoder_out_embedding_size, hparams.trg_embedding_size)
            self.fc_last = nn.Linear(hparams.decoder_out_embedding_size, self.task.TargetVocabSize)
            self.fc_last.weight = self.embed_tokens.weight
        else:
            self.fc_last = Linear(hparams.decoder_out_embedding_size,
                                  self.task.TargetVocabSize, dropout=hparams.dropout, hparams=hparams)

    def _embed_tokens(self, tokens, incremental_state):
        if incremental_state is not None:
            # Keep only the last token for incremental forward pass
            tokens = tokens[:, -1:]
        return self.embed_tokens(tokens)

    def _split_encoder_out(self, encoder_out, incremental_state):
        """Split and transpose encoder outputs.

        This is cached when doing incremental inference.
        """
        cached_result = common.get_incremental_state(self, incremental_state, 'encoder_out')
        if cached_result is not None:
            return cached_result

        # transpose only once to speed up attention layers
        if self.hparams.enc_dec_attn_type == 'fairseq':
            # [NOTE]: Only do transpose here for fairseq attention
            encoder_a, encoder_b = encoder_out
            encoder_a = encoder_a.transpose(1, 2).contiguous()
            result = (encoder_a, encoder_b)
        else:
            result = encoder_out

        if incremental_state is not None:
            common.set_incremental_state(self, incremental_state, 'encoder_out', result)
        return result

    @staticmethod
    def get_normalized_probs(net_output, log_probs=False):
        logits = net_output[0]
        if log_probs:
            return F.log_softmax(logits, dim=-1)
        else:
            return F.softmax(logits, dim=-1)

    def upgrade_state_dict(self, state_dict):
        return state_dict

    def max_positions(self):
        return self.embed_positions.max_positions()


def _forward_call(method_name):
    def _method(self, *args, **kwargs):
        return getattr(self.module, method_name)(*args, **kwargs)
    return _method


class ParalleledChildNet(nn.DataParallel):
    encode = _forward_call('encode')
    decode = _forward_call('decode')
    get_normalized_probs = _forward_call('get_normalized_probs')
    get_targets = _forward_call('get_targets')
    max_encoder_positions = _forward_call('max_encoder_positions')
    max_decoder_positions = _forward_call('max_decoder_positions')
    upgrade_state_dict = _forward_call('upgrade_state_dict')
    num_parameters = _forward_call('num_parameters')


__all__ = [
    'ChildNetBase',
    'EncDecChildNet',

    'ChildDecoderBase',

    'ParalleledChildNet',
]