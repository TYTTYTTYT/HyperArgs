from hyperargs import Conf, add_dependency, monitor_on
from hyperargs.args import IntArg, FloatArg, StrArg, BoolArg, OptionArg

class AdamConf(Conf):
    lr = FloatArg(0.001, min_value=1e-6, max_value=1.0)
    beta1 = FloatArg(0.9, min_value=0.0, max_value=1.0)
    beta2 = FloatArg(0.999, min_value=0.0, max_value=1.0)
    epsilon = FloatArg(1e-8, min_value=0.0)


class SGDConf(Conf):
    lr = FloatArg(0.001, min_value=1e-6, max_value=1.0)
    momentum = FloatArg(0.0, min_value=0.0, max_value=1.0)


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
    master_addr = StrArg("127.0.0.1", env_bind="MASTER_ADDR")

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

if __name__ == "__main__":
    conf = TrainConf.parse_command_line()
    print("The config is:", conf)
