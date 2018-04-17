#! /usr/bin/python
# -*- coding: utf-8 -*-

import argparse

import torch

from ..hparams import get_hparams
from ..layers import lstm, cnn, attention
from ..optimizers import AllOptimizers
from ..optimizers.lr_schedulers import AllLRSchedulers
from ..criterions import AllCriterions

__author__ = 'fyabc'


def add_general_args(parser):
    group = parser.add_argument_group('General Options', description='General options.')
    group.add_argument('--log-level', dest='logging_level', type=str, default='INFO', metavar='LEVEL',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='logging level, default is %(default)s')
    group.add_argument('-H', '--hparams-set', dest='hparams_set', type=str, default='base')
    group.add_argument('-T', '--task', dest='task', type=str, default='test')
    group.add_argument('--seed', dest='seed', type=int, default=1, metavar='N',
                       help='pseudo random number generator seed')
    group.add_argument('-N', '--net-code-file', dest='net_code_file', type=str, metavar='FILE',
                       help='net code filename')
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
    group.add_argument('--lstm-space', dest='lstm_space', type=str, default=None,
                       choices=lstm.Spaces.keys(),
                       help='LSTM search space: {}'.format(', '.join(lstm.Spaces.keys())))
    group.add_argument('--conv-space', dest='conv_space', type=str, default=None,
                       choices=cnn.Spaces.keys(),
                       help='Convolutional search space: {}'.format(', '.join(cnn.Spaces.keys())))
    group.add_argument('--attn-space', dest='attn_space', type=str, default=None,
                       choices=attention.Spaces.keys(),
                       help='Attention search space: {}'.format(', '.join(attention.Spaces.keys())))
    return group


def add_dataset_args(parser, train=False, gen=False):
    group = parser.add_argument_group('Dataset Options:')
    group.add_argument('-b', '--max-sentences', '--batch-size', dest='max_sentences', type=int, metavar='N',
                       help='maximum number of sentences in a batch')
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
                       help='training criterion: {} (default: cross_entropy)'.format(
                           ', '.join(AllCriterions.keys())))
    group.add_argument('--max-epoch', '--me', default=0, type=int, metavar='N',
                       help='force stop training at specified epoch, default is inf')
    group.add_argument('--max-update', '--mu', default=0, type=int, metavar='N',
                       help='force stop training at specified update, default is inf')
    group.add_argument('--max-tokens', default=6000, type=int, metavar='N',
                       help='maximum number of tokens in a batch')
    group.add_argument('--clip-norm', default=25, type=float, metavar='NORM',
                       help='clip threshold of gradients')
    group.add_argument('--sentence-avg', action='store_true', default=False,
                       help='normalize gradients by the number of sentences in a batch'
                            ' (default is to normalize by number of tokens)')
    group.add_argument('--optimizer', default='nag', metavar='OPT',
                       choices=AllOptimizers.keys(),
                       help='optimizer: {} (default: nag)'.format(', '.join(AllOptimizers.keys())))
    group.add_argument('--lr', '--learning-rate', default='0.25', metavar='LR_1,LR_2,...,LR_N',
                       help='learning rate for the first N epochs; all epochs >N using LR_N'
                            ' (note: this may be interpreted differently depending on --lr-scheduler)')
    group.add_argument('--momentum', default=0.99, type=float, metavar='M',
                       help='momentum factor')
    group.add_argument('--weight-decay', '--wd', default=0.0, type=float, metavar='WD',
                       help='weight decay')

    group.add_argument('--lr-scheduler', default='reduce_lr_on_plateau',
                       help='learning rate scheduler: {} (default: reduce_lr_on_plateau)'.format(
                           ', '.join(AllLRSchedulers.keys())))
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
                            'establish initial connetion')
    group.add_argument('--distributed-port', default=-1, type=int,
                       help='port number (not required if using --distributed-init-method)')
    group.add_argument('--device-id', type=int, default=0, metavar='N',
                       help='GPU device id, usually automatically set')
    return group


def add_checkpoint_args(parser):
    group = parser.add_argument_group('Checkpoint Options')
    group.add_argument('--restore-file', default='checkpoint_last.pt',
                       help='Filename in model directory from which to load checkpoint, '
                            'default is %(default)s')
    group.add_argument('--save-interval', type=int, default=-1, metavar='N',
                       help='save a checkpoint every N updates')
    group.add_argument('--no-save', action='store_true', default=False,
                       help='don\'t save models and checkpoints')
    group.add_argument('--no-epoch-checkpoints', action='store_true',
                       help='only store last and best checkpoints')
    group.add_argument('--validate-interval', type=int, default=1, metavar='N',
                       help='validate every N epochs')
    return group


def get_args(args=None):
    parser = argparse.ArgumentParser(description='Training Script.')

    add_general_args(parser)
    add_hparams_args(parser)
    add_dataset_args(parser, train=True)
    add_train_args(parser)
    add_distributed_args(parser)
    add_checkpoint_args(parser)

    parsed_args = parser.parse_args(args)
    base_hparams = get_hparams(parsed_args.hparams_set)

    # Set default value of hparams.
    for name, value in base_hparams.__dict__.items():
        if getattr(parsed_args, name, None) is None:
            setattr(parsed_args, name, value)

    # Post process args.
    parsed_args.lr = list(map(float, parsed_args.lr.split(',')))
    if parsed_args.max_sentences_valid is None:
        parsed_args.max_sentences_valid = parsed_args.max_sentences

    return parsed_args
