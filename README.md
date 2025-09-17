# HyperArgs

**HyperArgs** is a typed configuration library for Python.  
It lets you define hyperparameters and settings as strongly typed Python classes, parse them from multiple sources (command line, JSON, TOML, YAML), enforce dependency constraints, and monitor field changes with decorators.  

HyperArgs provides:
- **Typed arguments** — `IntArg`, `FloatArg`, `StrArg`, `BoolArg`, `OptionArg`.  
- **Config classes** — subclass `Conf` to declare structured, type-safe settings.  
- **Multi-source parsing** — load from CLI, JSON, TOML, YAML, or dict.  
- **Dependency management** — declare relationships between fields.  
- **Change monitoring** — automatically trigger updates when fields change.  
- **Environment variable binding** — args can bind to env vars via `env_bind`.  

## Installation

```bash
pip install hyperargs
```

## Quick Start

### 1. Define a configuration

```python
# file: train.py

from hyperargs import Conf, add_dependency, monitor_on
from hyperargs.args import IntArg, FloatArg, StrArg, BoolArg, OptionArg

class TrainConf(Conf):
    learning_rate = FloatArg(0.001, min_value=1e-6, max_value=1.0)
    batch_size = IntArg(32, min_value=1)
    num_epochs = IntArg(10, min_value=1)
    optimizer = OptionArg("adam", options=["adam", "sgd", "rmsprop"])
    use_gpu = BoolArg(True)

    @monitor_on("learning_rate")
    def adjust_schedule(self):
        print(f"Learning rate changed to {self.learning_rate.value()}")

conf = TrainConf.parse_command_line(strict=True)
print(conf)

...
```

---

### 2. Parse configurations

- From command line:

```python
python train.py --config_path config.yaml
```
Supported formats: .json, .toml, .yaml, .yml.

- From Python dict:

```python
conf = TrainConf.from_dict({"learning_rate": 0.01, "batch_size": 64})
print(conf.to_yaml())
```

---

### 3. Save configurations

```python
conf.save_to_file("config.json")
```
Supported formats: .json, .toml, .yaml, .yml.

---

### 4. Add dependencies
For example, you may want to ensure that the optimizer type is set before its corresponding optimizer config.

```python
class OptimizerConf(Conf):
    lr: FloatArg(1e-3)

class AdamConf(OptimizerConf):
    beta1 = FloatArg(0.9)
    beta2 = FloatArg(0.999)

class SGDConf(OptimizerConf):
    momentum = FloatArg(0.9)

# Ensure optimizer type is decided first, then configs are parsed
@Conf.add_dependency("optim_type", "configs")
class OptimConf(Conf):
    optim_type = OptionArg("adam", options=["adam", "sgd"])
    configs = OptimizerConf()

    # Switch the config to the correct type when optim_type is being setted
    @Conf.monitor_on('optim_type')
    def init_configs(self) -> None:
        if self.optim_type.value() == 'adam':
            self.configs = AdamConf()
        elif self.optim_type.value() == 'sgd':
            self.configs = SGDConf()
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
	- BoolArg(default, allow_none=False, env_bind=None)
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

### Stage 2 — Command line flags 🚧
- Parse configs directly from CLI flags  
  (e.g. `--optimizer.params.learning_rate 0.01 --batch_size 64`)

### Stage 3 — GUI settings 🚧
- Popup browser page to set configs interactively
- Export configs after editing

## License

Apache License 2.0
