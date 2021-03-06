#! /usr/bin/python
# -*- coding: utf-8 -*-

"""Convert net code between different formats.

See ``NetCodeFormat.md`` for details of net code.
"""

from copy import deepcopy
import itertools
import json
import logging
import os
import pickle
import re

from ..utils.registry_utils import camel2snake
from ..utils.search_space import GlobalSpace

__author__ = 'fyabc'


class NetCode:
    """The net code class, which contains global code and layers code."""

    # TODO: Support format of same (shared) block layer code, and add to doc

    # Net code types.
    Default = 'ChildNet'
    BlockChildNet = 'BlockChildNet'

    def __init__(self, net_code):
        self.original_code = deepcopy(net_code)

        if isinstance(net_code, list):
            # Compatible with old net code.
            self.global_code = {}
            self.layers_code = net_code
            self.type = self.Default
        elif isinstance(net_code, dict):
            self.global_code = net_code.get('Global', {})
            self.layers_code = net_code.get('Layers', [])
            self.type = net_code.get('Type', self.Default)
        else:
            raise TypeError('Incorrect net code type {}'.format(type(net_code)))

        if self.type == self.BlockChildNet:
            self.blocks = net_code.get('Blocks', {})
            for layers_code_ed in self.layers_code:
                for i in range(len(layers_code_ed)):
                    layer_code = layers_code_ed[i]
                    # Retrieve blocks.
                    if isinstance(layer_code, str):
                        try:
                            layers_code_ed[i] = self.blocks[layer_code]
                        except KeyError as e:
                            raise RuntimeError('Unknown block name {!r}'.format(layer_code)) from e

        self.check_correctness()

    def __getitem__(self, item):
        return self.layers_code[item]

    def __len__(self):
        return len(self.layers_code)

    def __eq__(self, other):
        cls = type(self)
        if not isinstance(other, cls):
            if isinstance(other, (list, dict)):
                other = cls(other)
        return self.global_code == other.global_code and \
            self.layers_code == other.layers_code and \
            self.type == other.type

    def fast_eq(self, other):
        """Fast equal test for NAO generated net code.

        Assume that:
            Block type same
            Blocks are all "enc1" and "dec1"
            #Layers are same
        """
        return self.global_code == other.global_code and \
            self.blocks['enc1'] == other.blocks['enc1'] and self.blocks['dec1'] == other.blocks['dec1']

    def check_correctness(self):
        # TODO
        pass

    def modify_hparams(self, hparams):
        """Modify the hparams with the global net code.

        [NOTE]: The hparams priority:
            (Low)   Values defined in ``get_hparams(hparams.hparams_set)``;
                    Values defined in global net code;
            (High)  Values defined in command line.

        Args:
            hparams:

        Returns:

        """
        for name, index in self.global_code.items():
            c_name = camel2snake(name)
            if getattr(hparams, c_name, None) is None:
                value = getattr(GlobalSpace, name)[index]
                setattr(hparams, c_name, value)
                logging.info('Overwrite hparam {!r} to value {!r}'.format(c_name, value))

    @classmethod
    def convert_old(cls, old_code):
        if old_code is None:
            return None

        if isinstance(old_code, (list, dict)):
            return cls(old_code)

        if not hasattr(old_code, 'global_code'):
            setattr(old_code, 'global_code', {})
        if not hasattr(old_code, 'type'):
            setattr(old_code, 'type', cls.Default)
        return old_code


def dump_json(net_code, fp):
    json.dump(net_code, fp)


def load_json(fp):
    """Load net code from JSON file, remove line comments."""
    return json.loads(''.join(re.sub(r'//.*\n', '\n', _line) for _line in fp))


def load_pickle(fp):
    return pickle.load(fp)


def load_net_code_from_file(filename):
    base, ext = os.path.splitext(filename)

    # If there is a colon in filename ("a:14.json"), it means to read line 14 from a.json.
    colon_pos = base.rfind(':')
    line_no = None
    if colon_pos != -1:
        line_no = int(base[colon_pos + 1:])
        filename = base[:colon_pos] + ext

    if ext in ('.json', '.txt'):
        mode = 'r'
    elif ext == '.pkl':
        mode = 'rb'
    else:
        raise ValueError('Does not support this net code file format now')

    with open(filename, mode) as f:
        lines = f
        if line_no is not None:
            lines = itertools.islice(lines, line_no - 1, line_no)

        if ext in ('.json', '.txt'):
            code = load_json(lines)
        elif ext == '.pkl':
            code = load_pickle(lines)
        else:
            raise ValueError('Does not support this net code file format now')

        return NetCode(code)


def get_net_code(hparams, modify_hparams=True):
    """Get net code from path given by hparams.

    Args:
        hparams:
        modify_hparams: Modify the hparams with the given (global) net code.

    Returns:

    """
    result = load_net_code_from_file(hparams.net_code_file)
    # Replace illegal characters.
    hparams.net_code_file = hparams.net_code_file.replace(':', '_')
    if modify_hparams:
        result.modify_hparams(hparams)
    return result
