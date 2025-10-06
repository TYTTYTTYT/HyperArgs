# HyperArgs

**HyperArgs** HyperArgs is a typed configuration library with automatic WEB GUI for Python.

It lets you define hyperparameters and settings as strongly typed Python classes, parse them from multiple sources (command line, JSON, TOML, YAML) or configure them from a WEB GUI interface, enforce dependency constraints, and monitor field changes with decorators.  

## Quick Start

### 1. Install

```bash
pip install hyperargs
```

---

### 2. Have a try

- **(Recommand!)** From GUI interface:

```bash
python example/example.py --from_web
```
You can save the configuration to a file after you have configured it.

![demo](example/demo.gif)

- From saved configuration file:

```bash
python example/example.py --config_path example/TrainConf.toml
```
Supported formats: .json, .toml, .yaml, .yml.

- From command line flags:

```bash
python train.py --parse_json '{
  "batch_size": 32,
  "num_epochs": 10,
  "optimizer_conf": {
    "lr": 5e-5,
    "momentum": 0.04
  },
  "optimizer_type": "sgd",
  "use_gpu": true
}'
```

---

### 3. Config dependencies

Many programs require dynamic dependencies between fields. HyperArgs lets you define monitors and dependencies between fields to dynamically update fields when value changes.

In the `example.py`, the config of `optimizer_conf` depends on `optimizer_type`. Thus we add a monitor method `change_optimizer` to switch the config to the correct type when `optimizer_type` is being setted.

During the initialization or parsing process, the monitors will be triggered to update the dependent fields. To ensure that the conditioned fields gets updated correctly, you should set the dependency order correctly. In the example.py, we set the dependency order as `optimizer_type -> int_arg -> len_lst`. So the `change_optimizer` monitor will be triggered before parsing arguments for the `optimizer_conf`.

In another case, the value of `conditioned_arg` depends on `int_arg`. Thus we add the dependency `conditioned_arg -> int_arg`. During the parsing process, the `change_b` monitor will be triggered after parsing the `conditioned_arg`, so the `conditioned_arg` will be updated according to the value of `int_arg` rather than the default value.

```python
@add_dependency("optimizer_type", "optimizer_conf")
@add_dependency("conditioned_arg", "int_arg")
@add_dependency("len_lst", "lst")
class TrainConf(Conf):
    message = StrArg("Hello World!")
    batch_size = IntArg(32, min_value=1)
    num_epochs = IntArg(10, min_value=1)
    optimizer_type = OptionArg("adam", options=["adam", "sgd"])
    use_gpu = BoolArg(True)
    optimizer_conf = Conf()

    int_arg = IntArg(100)
    conditioned_arg = IntArg(200)
    len_lst = IntArg(0, min_value=0)
    lst = []

    @monitor_on("optimizer_type")   # Change "optimizer_conf" when "optimizer_type" changes
    def change_optimizer(self):
        if self.optimizer_type.value() == "adam":
            if not isinstance(self.optimizer_conf, AdamConf):
                self.optimizer_conf = AdamConf()
        elif self.optimizer_type.value() == "sgd":
            if not isinstance(self.optimizer_conf, SGDConf):
                self.optimizer_conf = SGDConf()

    @monitor_on("int_arg")  # Change "conditioned_arg" when "int_arg" changes
    def change_b(self):
        v = self.int_arg.value()
        if v is not None:
            self.conditioned_arg = self.conditioned_arg.parse(v * 2)

    @monitor_on("len_lst")  # Change "lst" when "len_lst" changes
    def change_lst(self):
        len_lst = self.len_lst.value()
        if len_lst is not None:
            if len(self.lst) > len_lst:
                self.lst = self.lst[:len_lst]
            elif len(self.lst) < len_lst:
                self.lst.extend([SGDConf() for _ in range(len_lst - len(self.lst))])

```

---

### 5. Environment variable binding

Arguments can bind directly to environment variables.
For example, setting the MASTER_ADDR for distributed training:

```python
import os
os.environ["MASTER_ADDR"] = "192.168.1.42"

class DistConf(Conf):
    master_addr = StrArg("127.0.0.1", env_bind="MASTER_ADDR")

conf = DistConf()
print(conf.master_addr.value())  # "192.168.1.42"
```

## API Overview

You can import the main API directly:
```python
from hyperargs import Conf, add_dependency, monitor_on
from hyperargs.args import IntArg, FloatArg, StrArg, BoolArg, OptionArg
```

* **Arg subclasses**
    - IntArg(default, min_value=None, max_value=None, allow_none=False, env_bind=None)
	- FloatArg(default, min_value=None, max_value=None, allow_none=False, env_bind=None)
	- StrArg(default, allow_none=False, env_bind=None)
	- BoolArg(default, env_bind=None)
	- OptionArg(default, options, allow_none=False, env_bind=None)
* **Conf** — base class for config schemas.
* **monitor_on(fields)** — decorator to watch fields and trigger methods.
* **add_dependency(parent, child)** — enforce field dependency order.

## Example Workflow
```yaml
# config.yaml
learning_rate: 0.01
batch_size: 64
num_epochs: 20
optimizer: sgd
use_gpu: false
```
```python
conf = TrainConf.parse_command_line()
# run: python train.py --config_path config.yaml
print(conf.optimizer.value())  # "sgd"
```

## Roadmap

### Stage 1 — Config files & strings ✅
- Parse from JSON, TOML, YAML strings
- Parse from config files
- Convert and save configs

### Stage 2 — GUI settings ✅
- Popup browser page to set configs interactively
- Export configs after editing

### Stage 3 — Command line flags 🚧
- Parse configs directly from CLI flags  
  (e.g. `--optimizer.params.learning_rate 0.01 --batch_size 64`)

## License

Apache License 2.0
