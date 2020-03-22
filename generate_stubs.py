# This Python file uses the following encoding: utf-8
#############################################################################
##
# Copyright (C) 2019 The Qt Company Ltd.
# Contact: https://www.qt.io/licensing/
##
# This file is part of Qt for Python.
##
# $QT_BEGIN_LICENSE:LGPL$
# Commercial License Usage
# Licensees holding valid commercial Qt licenses may use this file in
# accordance with the commercial license agreement provided with the
# Software or, alternatively, in accordance with the terms contained in
# a written agreement between you and The Qt Company. For licensing terms
# and conditions see https://www.qt.io/terms-conditions. For further
# information use the contact form at https://www.qt.io/contact-us.
##
# GNU Lesser General Public License Usage
# Alternatively, this file may be used under the terms of the GNU Lesser
# General Public License version 3 as published by the Free Software
# Foundation and appearing in the file LICENSE.LGPL3 included in the
# packaging of this file. Please review the following information to
# ensure the GNU Lesser General Public License version 3 requirements
# will be met: https://www.gnu.org/licenses/lgpl-3.0.html.
##
# GNU General Public License Usage
# Alternatively, this file may be used under the terms of the GNU
# General Public License version 2.0 or (at your option) the GNU General
# Public license version 3 or any later version approved by the KDE Free
# Qt Foundation. The licenses are as published by the Free Software
# Foundation and appearing in the file LICENSE.GPL2 and LICENSE.GPL3
# included in the packaging of this file. Please review the following
# information to ensure the GNU General Public License requirements will
# be met: https://www.gnu.org/licenses/gpl-2.0.html and
# https://www.gnu.org/licenses/gpl-3.0.html.
##
# $QT_END_LICENSE$
##
##
# This file was a modified copy from
# [Qt for Python](https://wiki.qt.io/Qt_for_Python) project, and is edited
# for generating python stubs that are compatible to mypy.
##
# modified by @HareInWeed (https://github.com/HareInWeed)
##
# Notice: unlike the original version, this script can not run under
# Python 2
#############################################################################

"""
generate_stubs.py

This script generates mypy compatible stubs for PySide2
"""

import sys
import os
import io
import re
from pathlib import Path
import subprocess
import argparse
from contextlib import contextmanager
from textwrap import dedent
from enum import Enum, auto as enumAuto
from typing import Any, Dict, Set, List
import logging

PySide2: Any
inspect: Any
typing: Any
HintingEnumerator: Any
build_brace_pattern: Any


class StubStyle(Enum):
    Absolute = enumAuto()
    Relative = enumAuto()
    AllRelative = enumAuto()


ExternalT = Dict[str, Set[str]]

src_module = "PySide2"
src_module_regex = re.compile(fr'\b{src_module}\b')

# Make sure not to get .pyc in Python2.
sourcepath = os.path.splitext(__file__)[0] + ".py"

# Can we use forward references?
USE_PEP563 = sys.version_info[:2] >= (3, 7)

indent = " " * 4
is_py3 = sys.version_info[0] == 3
is_ci = os.environ.get("QTEST_ENVIRONMENT", "") == "ci"
is_debug = is_ci or os.environ.get("QTEST_ENVIRONMENT")

logging.basicConfig(level=logging.DEBUG if is_debug else logging.INFO)
logger = logging.getLogger("generate_pyi")

shiboken_object_regex = re.compile(r"\bShiboken\.Object\b")
module_regex = re.compile(fr"\b{src_module}\.(\w+\.\w+|\w+)\b")
module_ref_regex = re.compile(fr"\b{src_module}\.(\w+\.?)\b")
typing_char_regex = re.compile(fr"\btyping\.Char\b")
typing_ordered_dist_regex = re.compile(fr"\btyping\.OrderedDict\b")
init_with_return_regex = re.compile(r"\b(\([^\)]+\))\s*->")


def echo(_):
    # for debug only
    print(_)
    return _


def sub_shiboken_object(_): return shiboken_object_regex.sub(r'object', _)


class Writer(object):
    def __init__(self, outfile):
        self.outfile = outfile

        self.max_history_size = 1000
        self.min_history_size = 2
        self.history = [True] * self.min_history_size

    def update_history(self, isBlankLine):
        if len(self.history) >= self.max_history_size:
            self.history = self.history[-self.min_history_size-1:0]
        self.history.append(isBlankLine)

    def print(self, *args, **kw):
        # controlling too much blank lines
        if self.outfile:
            if args == () or args == ("",):
                # Python 2.7 glitch: Empty tuples have wrong encoding.
                # But we use that to skip too many blank lines:
                if self.history[-2:] == [True, True]:
                    return
                print("", file=self.outfile, **kw)
                self.update_history(True)
            else:
                print(*args, file=self.outfile, **kw)
                self.update_history(False)


class Formatter(Writer):
    """
    Formatter is formatting the signature listing of an enumerator.

    It is written as context managers in order to avoid many callbacks.
    The separation in formatter and enumerator is done to keep the
    unrelated tasks of enumeration and formatting apart.
    """

    def __init__(self, outfile, dist_module: str, style: StubStyle, ignore: bool):
        super().__init__(outfile)
        # patching __repr__ to disable the __repr__ of typing.TypeVar:
        """
            def __repr__(self):
                if self.__covariant__:
                    prefix = '+'
                elif self.__contravariant__:
                    prefix = '-'
                else:
                    prefix = '~'
                return prefix + self.__name__
        """

        self.dist_module = dist_module
        # TODO
        self.style = style
        # regex to remove self import
        self.mod_name_regex = None
        # external dependencies
        self.externals: ExternalT = {}
        self.extra_import: Set[str] = set()
        if ignore:
            self.ignore = " # type: ignore[misc, override]"
        else:
            self.ignore = ""

        def _typevar__repr__(self):
            return "typing." + self.__name__
        typing.TypeVar.__repr__ = _typevar__repr__

        # Adding a pattern to substitute "Union[T, NoneType]" by "Optional[T]"
        # I tried hard to replace typing.Optional by a simple override, but
        # this became _way_ too much.
        # See also the comment in layout.py .
        brace_pat = build_brace_pattern(3)

        optional_searcher = re.compile(
            fr"\b Union \s* \[ \s* {brace_pat} \s*, \s* NoneType \s* \]", flags=re.VERBOSE)

        def optional_replacer(source):
            return optional_searcher.sub(r"Optional[\1]", str(source))
        self.optional_replacer = optional_replacer

        # remove ineffective Missing(...)
        missing_searcher = re.compile(
            fr"(:\s*|\s*->\s*)Missing\({brace_pat}\)", flags=re.VERBOSE)

        def missing_replacer(source):
            return missing_searcher.sub(r"", str(source))
        self.missing_replacer = missing_replacer

        # self.level is maintained by enum_sig.py
        # self.after_enum() is a one-shot set by enum_sig.py .

    def _remove_self_import(self, code: str) -> str:
        if self.mod_name_regex is not None:
            code = self.mod_name_regex.sub(r'', code)
        return code

    def _fix_typing_char(self, code: str) -> str:
        code = typing_char_regex.sub(r'typing.AnyStr', code)
        return code

    def _fix_typing_ordered_dict(self, code: str) -> str:
        if typing_ordered_dist_regex.search(code) is not None:
            code = typing_ordered_dist_regex.sub(r'OrderedDict', code)
            self.extra_import.add("from collections import OrderedDict")
        return code

    def _rename_module(self, code: str) -> str:
        if src_module != dist_module:
            code = src_module_regex.sub(dist_module, code)
        return code

    def _change_style(self, code: str) -> str:
        """
        change stub import style and collect external dependency info
        notice this function must be called before `_rename_module`
        """
        if self.style != StubStyle.Absolute:
            for elem in module_regex.findall(code):
                parts: List[str] = elem.split('.')
                name = parts[0]
                if self.style == StubStyle.AllRelative:
                    self.externals.setdefault(name, set()).update(parts[1:])
                else:
                    self.externals.setdefault(name)
            if self.style == StubStyle.AllRelative:
                code = module_ref_regex.sub(r'', code)
            elif self.style == StubStyle.Relative:
                code = module_ref_regex.sub(r'\1', code)
        return code

    def preProcess(self, code: Any) -> str:
        code_ = str(code)
        code_ = self._remove_self_import(code_)
        code_ = self._fix_typing_char(code_)
        code_ = self._fix_typing_ordered_dict(code_)
        code_ = self._change_style(code_)
        code_ = self._rename_module(code_)
        return code_

    @contextmanager
    def module(self, mod_name):
        self.mod_name = mod_name
        self.mod_name_regex = re.compile(fr'\b{mod_name}\.?\b')
        self.print(f"# Module {self._rename_module(mod_name)}")
        from PySide2.support.signature import typing
        self.print("import typing")
        self.print()
        # This line will be replaced by the missing imports postprocess.
        self.print("IMPORTS")
        yield

    @contextmanager
    def klass(self, class_name, class_str):
        spaces = indent * self.level
        while "." in class_name:
            class_name = class_name.split(".", 1)[-1]
            class_str = class_str.split(".", 1)[-1]
        class_str = sub_shiboken_object(class_str)
        class_str = self.preProcess(class_str)
        self.print()
        if self.level == 0:
            self.print()
        here = self.outfile.tell()
        if self.have_body:
            self.print(f"{spaces}class {class_str}:")
        else:
            self.print(f"{spaces}class {class_str}: ...")
        yield
        if "<" in class_name:
            # This is happening in QtQuick for some reason:
            # class QSharedPointer<QQuickItemGrabResult >:
            # We simply skip over this class.
            self.outfile.seek(here)
            self.outfile.truncate()

    @contextmanager
    def function(self, func_name, signature, modifier=None):
        if self.after_enum() or func_name == "__init__":
            self.print()
        key = func_name
        spaces = indent * self.level
        if isinstance(signature, list):
            for sig in signature:
                if not self._function_filter(func_name, signature):
                    continue
                sig = self.preProcess(sig)
                # temporary solution, ignore error directly
                self.print(
                    f'{spaces}@typing.overload{self.ignore}')
                self._function(func_name, sig, modifier, spaces)
        else:
            if self._function_filter(func_name, signature):
                self._function(func_name, self.preProcess(
                    signature), modifier, spaces)
        if func_name == "__init__":
            self.print()
        yield key

    def _function_filter(self, func_name: str, signature):
        return not (func_name in ["__repr__", "__reduce__", "__str__"] and signature.return_annotation == object)

    def _fix_init_return(self, func_name: str, sig: str) -> str:
        sig = str(sig)
        if func_name == "__init__":
            return init_with_return_regex.sub(r"\1", sig)
        else:
            return sig

    def _function(self, func_name, signature, modifier, spaces):
        if modifier:
            self.print(f'{spaces}@{modifier}')
        signature = self._fix_init_return(func_name, signature)
        signature = self.missing_replacer(signature)
        signature = self.optional_replacer(signature)
        # temporary solution, ignore error directly
        self.print(
            f'{spaces}def {func_name}{signature}: ...{self.ignore}')

    @contextmanager
    def enum(self, class_name, enum_name, value):
        spaces = indent * self.level
        hexval = hex(value)
        self.print(f"{spaces}{enum_name:25}: {class_name} = ... # {hexval}")
        yield


def get_license_text():
    with io.open(sourcepath) as f:
        lines = f.readlines()
        license_line = next((lno for lno, line in enumerate(lines)
                             if "$QT_END_LICENSE$" in line))
    return "".join(lines[:license_line + 3])


def find_external(code: List[str], style: StubStyle) -> ExternalT:
    externals: ExternalT = {}
    for line in code:
        for elem in module_regex.findall(line):
            parts: List[str] = elem.split('.')
            name = parts[0]
            if style == StubStyle.AllRelative:
                externals.setdefault(name, set()).update(parts[1:])
            else:
                externals.setdefault(name)
    return externals


def generate_pyi(import_name, dist_module: str, outpath: Path, style: StubStyle, ignore: bool, options):
    """
    Generates a .pyi file.
    """
    plainname = import_name.split(".")[-1]
    outfilepath = outpath / f"{plainname}.pyi"
    top = __import__(import_name)
    obj = getattr(top, plainname)
    if not getattr(obj, "__file__", None) or Path(obj.__file__).is_dir():
        raise ModuleNotFoundError(
            f"We do not accept a namespace as module {plainname}")
    module = sys.modules[import_name]

    outfile = io.StringIO()
    fmt = Formatter(outfile, dist_module, style, ignore)
    fmt.print(get_license_text())  # which has encoding, already
    need_imports = not USE_PEP563
    if USE_PEP563:
        fmt.print("from __future__ import annotations")
        fmt.print()
    fmt.print(dedent(f'''\
        """
        This file contains the exact signatures for all functions in module
        {import_name}, except for defaults which are replaced by "...".
        """
        '''))
    HintingEnumerator(fmt).module(import_name)
    fmt.print()
    fmt.print("# eof")
    # Postprocess: resolve the imports

    with outfilepath.open("w") as realfile:
        wr = Writer(realfile)
        outfile.seek(0)
        for line in outfile:
            line = line.rstrip()
            # we remove the IMPORTS marker and insert imports if needed
            if line == "IMPORTS":
                for imp in fmt.extra_import:
                    wr.print(imp)
                wr.print()
                if style == StubStyle.Absolute:
                    wr.print(f"import {dist_module}")
                else:
                    for mod_name, elem in fmt.externals.items():
                        if style == StubStyle.Relative:
                            wr.print(f"from . import {mod_name}")
                        else:
                            wr.print(
                                f"from .{mod_name} import {', '.join(elem)}")
                wr.print()
                wr.print()
            elif "class QPaintDeviceWindow" in line:
                # specific patch for `class QPaintDeviceWindow`
                wr.print(line)
                wr.print(
                    "    def devicePixelRatio(self) -> float: ... # type: ignore[override]")
            else:
                wr.print(line)
    logger.info(f"Generated: {outfilepath}")
    if is_py3 and (options.check or is_ci):
        # Python 3: We can check the file directly if the syntax is ok.
        subprocess.check_output([sys.executable, outfilepath])


def generate_all_pyi(outpath, dist_module: str, style: StubStyle, ignore: bool, options):
    ps = os.pathsep
    if options.sys_path:
        # make sure to propagate the paths from sys_path to subprocesses
        sys_path = [str(Path(_).resolve().absolute())
                    for _ in options.sys_path]
        sys.path[0:0] = sys_path
        os.environ["PYTHONPATH"] = ps.join(sys_path)

    # now we can import
    global PySide2, inspect, typing, HintingEnumerator, build_brace_pattern
    import PySide2
    from PySide2.support.signature import inspect, typing
    from PySide2.support.signature.lib.enum_sig import HintingEnumerator
    from PySide2.support.signature.lib.tool import build_brace_pattern

    # propagate USE_PEP563 to the mapping module.
    # Perhaps this can be automated?
    PySide2.support.signature.mapping.USE_PEP563 = USE_PEP563

    outpath = Path(outpath or __file__)
    if outpath.is_file():
        outpath = outpath.parent
    name_list = PySide2.__all__ \
        if options.modules == ["all"] else options.modules
    errors = ", ".join(set(name_list) - set(PySide2.__all__))
    if errors:
        raise ImportError(f"The module(s) '{errors}' do not exist")
    quirk1, quirk2 = "QtMultimedia", "QtMultimediaWidgets"
    if name_list == [quirk1]:
        logger.debug(
            f"Note: We must defer building of {quirk1}.pyi until {quirk2} is available")
        name_list = []
    elif name_list == [quirk2]:
        name_list = [quirk1, quirk2]
    for mod_name in name_list:
        import_name = f"{src_module}.{mod_name}"
        generate_pyi(import_name, dist_module, outpath, style, ignore, options)
    # generate __init__.pyi
    with (outpath / "__init__.pyi").open("w+") as initFile:
        print(f'__all__ = {repr(name_list)}', file=initFile)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="This script generates mypy compatible stubs for PySide2")
    parser.add_argument("modules", nargs="+",
                        help="'all' or the names of modules to build (QtCore QtGui etc.)")
    parser.add_argument("--quiet", action="store_true", help="Run quietly")
    parser.add_argument("--check", action="store_true",
                        help="Test the output if on Python 3")
    parser.add_argument("-s", "--style", choices=['absolute', 'relative', 'all_relative'], default='absolute',
                        help="stubs import style (default = absolute)")
    parser.add_argument("-o", "--outpath",
                        help="the output directory (default = parent of this script)")
    parser.add_argument("-m", "--module",
                        help=f"the output module name (default = {src_module})")
    parser.add_argument("--ignore-typing-err", action='store_true',
                        help='force mypy ignore stubs error by add "# type: ignore" comments')
    parser.add_argument("--sys-path", nargs="+",
                        help="a list of strings prepended to sys.path")
    options = parser.parse_args()

    if options.quiet:
        logger.setLevel(logging.WARNING)
    outpath = options.outpath
    if outpath and not os.path.exists(outpath):
        os.makedirs(outpath)
        logger.info(f"+++ Created path {outpath}")

    styleMapping = {
        "absolute": StubStyle.Absolute,
        "relative": StubStyle.Relative,
        "all_relative": StubStyle.AllRelative
    }
    style = styleMapping.get(options.style, StubStyle.Absolute)

    dist_module = options.module or src_module

    ignore = options.ignore_typing_err

    generate_all_pyi(outpath, dist_module, style, ignore, options=options)
# eof
