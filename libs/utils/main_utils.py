#! /usr/bin/python
# -*- coding: utf-8 -*-

"""Utilities for main entries."""

import logging
import pprint

import torch as th

from ..layers.net_code import get_net_code
from ..utils.data_processing import LanguageDatasets

__author__ = 'fyabc'


def main_entry(hparams, datasets=None, train=True):
    """General code of main entries.

    Args:
        hparams:
        datasets (LanguageDatasets): Preload datasets or None.
        train (bool): In training or generation.

    Returns:
        dict: Contains several components.
    """

    logging.basicConfig(
        format='[{levelname:<8}] {asctime}.{msecs:0>3.0f}: <{filename}:{lineno}> {message}',
        level=hparams.logging_level,
        style='{',
    )

    title = 'training' if train else 'generation'

    logging.info('Start single node {}'.format(title))
    logging.info('Task: {}'.format(hparams.task))
    logging.info('HParams set: {}'.format(hparams.hparams_set))
    logging.info('Child {} hparams:\n{}'.format(title, pprint.pformat(hparams.__dict__)))

    if train:
        if not th.cuda.is_available():
            raise RuntimeError('Want to training on GPU but CUDA is not available')
        th.cuda.set_device(hparams.device_id)

        th.manual_seed(hparams.seed)

    # Get net code
    net_code = get_net_code(hparams)
    logging.info('Net code information:')
    logging.info('LSTM search space: {}'.format(hparams.lstm_space))
    logging.info('Convolutional search space: {}'.format(hparams.conv_space))
    logging.info('Attention search space: {}'.format(hparams.attn_space))

    # Load datasets
    datasets = LanguageDatasets(hparams.task) if datasets is None else datasets
    logging.info('Dataset information:')
    _d_src = datasets.source_dict
    logging.info('Source dictionary [{}]: len = {}'.format(_d_src.language, len(_d_src)))
    _d_trg = datasets.target_dict
    logging.info('Source dictionary [{}]: len = {}'.format(_d_trg.language, len(_d_trg)))

    splits = ['train', 'dev'] if train else [hparams.gen_subset]
    datasets.load_splits(splits)
    for split in splits:
        logging.info('Split {}: len = {}'.format(split, len(datasets.splits[split])))

    return {
        'net_code': net_code,
        'datasets': datasets,
    }