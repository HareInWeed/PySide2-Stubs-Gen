# PySide2 Stubs Generator

Scripts to generate mypy compatible stubs for [PySide2](https://wiki.qt.io/Qt_for_Python).

PySide2 itself comes with stubs. But the built-in type declaration doesn't work well with Python Language Server(`pyls`) and `mypy`, that is why the repo is here.

Currently the generated stubs is not 100% type error free, so you might need to ignore those errors. Adding `--ignore-typing-err` parameter does the trick.

Theoretically, with proper configuration (perhaps some tinkering or text replacement), it can also generate stubs for PyQt5 or some abstract layer on Qt binding in python, such as Qt.py. But that is not tested and cannot be guaranteed.

Notice this is not the official typing support of PySide2.

## Usage

Beware, `generate_stubs.py` can not run under python2

```plaintext
usage: generate_stubs.py [-h] [--quiet] [--check] [-s STYLE] [-o OUTPATH]
                            [-m MODULE] [--ignore-typing-err]
                            [--sys-path SYS_PATH [SYS_PATH ...]]
                            modules [modules ...]

This script generates mypy compatible stubs for PySide2

positional arguments:
  modules               'all' or the names of modules to build (QtCore QtGui
                        etc.)

optional arguments:
  -h, --help            show this help message and exit
  --quiet               Run quietly
  --check               Test the output if on Python 3
  -s STYLE, --style STYLE
                        stubs import style: absolute, relative, all_relative
                        (default = absolute)
  -o OUTPATH, --outpath OUTPATH
                        the output directory (default = parent of this script)
  -m MODULE, --module MODULE
                        the output module name (default = PySide2)
  --ignore-typing-err   force mypy ignore stubs error by add "# type: ignore"
                        comments
  --sys-path SYS_PATH [SYS_PATH ...]
                        a list of strings prepended to sys.path
```
<details> 
<summary>P.S. The `style` here, refers to how stubs import dependencies within generated stubs. For example, ...</summary> 

when using `--style absolute`, the generated stubs for `QtWidgets.QWidget` will be

```python
import PySide2

class QWidget(PySide2.QtCore.QObject, PySide2.QtGui.QPaintDevice):
    ...
```

when using `--style relative`, it will be

```python
from . import QtCore
from . import QtGui

class QWidget(QtCore.QObject, QtGui.QPaintDevice):
    ...
```

when using `--style all_relative`, it will be

```python
from .QtCore import QObject
from .QtGui import QPaintDevice

class QWidget(QObject, QPaintDevice):
    ...
```
</details> 

### VSCode

Sadly, generated stubs doesn't works well with `pyls` and `mypy` at the same time. So in order to get the best result, you have to generate two different version, and config Python Extension and mypy to use the correct one.

To generate stubs for `pyls`, use:
```bash
python generate_stubs.py all -o the/stubs/directory/PySide2 -s absolute
```

then add `the/stubs/directory/` into `$PYTHONPATH` within the `.env` file for python extension to config pyls. You can archive this by adding

```json
"python.envFile": "path/to/.env",
```

in `.vscode/settings.json`, and adding

```plaintext
PYTHONPATH=the/stubs/directory
```

in the `.env` file, `path/to/.env`.

To generate stubs for mypy, use:
```bash
python generate_stubs.py all -o the/stubs/directory/PySide2 -s relative --ignore-typing-err
```

then you can add

```ini
[mypy]
mypy_path = the/stubs/directory
```

in your `mypy.ini`, to config mypy correctly

## Limitations

- due to the original typing info in PySide2, `PySide2.QtCore.Qt. ...` sometimes can not use as parameter. For instance

  ```python
  QWidget.setAttribute(Qt.WA_NoSystemBackground)
  ```

  doesn't pass the type check of mypy, even the code is absolutely valid. in order to fix this, you have to use

  ```python
  QWidget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
  ```

## License

[LGPL](LICENSE)