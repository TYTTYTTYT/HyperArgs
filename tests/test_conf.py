"""Regression tests for hyperargs.

Run:  python tests/test_conf.py

Two halves:
  * BEHAVIOUR — properties that already hold and must keep holding.
  * DEFECTS — each one fails on 0.1.3. They are all cases where a value the
    user wrote in their config file never reaches the object, which on a
    multi-day training job surfaces as "why did it train with the default?"
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from hyperargs import (  # noqa: E402
    Conf, StrArg, IntArg, FloatArg, BoolArg, OptionArg, add_dependency, monitor_on,
)

PASSED: list[str] = []
FAILED: list[str] = []


def case(fn):
    def run():
        try:
            fn()
            PASSED.append(fn.__name__)
            print(f'  PASS  {fn.__name__}')
        except Exception as e:
            FAILED.append(f'{fn.__name__}: {e}')
            print(f'  FAIL  {fn.__name__}: {e}')
    run.__name__ = fn.__name__
    return run


# --------------------------------------------------------------------------
# fixtures
# --------------------------------------------------------------------------

class SGDConf(Conf):
    lr = FloatArg(0.01)
    momentum = FloatArg(0.0)


class AdamConf(Conf):
    lr = FloatArg(0.001)
    beta1 = FloatArg(0.9)


@add_dependency('optimizer_type', 'optimizer_conf')
class TrainConf(Conf):
    optimizer_type = OptionArg('adam', options=['adam', 'sgd'])
    optimizer_conf = Conf()
    epochs = IntArg(10)

    @monitor_on('optimizer_type')
    def swap_optimizer(self) -> None:
        want = {'adam': AdamConf, 'sgd': SGDConf}[self.optimizer_type.value()]
        if self.optimizer_conf.__class__ is not want:
            self.optimizer_conf = want()


@add_dependency('num_paths', 'paths')
class DataConf(Conf):
    num_paths = IntArg(1)
    paths = [StrArg('a')]

    @monitor_on('num_paths')
    def resize_paths(self) -> None:
        n = self.num_paths.value()
        cur = list(self.paths)
        while len(cur) < n:
            cur.append(StrArg('a'))
        self.paths = cur[:n]


# --------------------------------------------------------------------------
# BEHAVIOUR — must keep working
# --------------------------------------------------------------------------

@case
def behaviour_nested_parses_when_trigger_present():
    c = TrainConf.from_dict({'optimizer_type': 'sgd',
                             'optimizer_conf': {'lr': 0.5, 'momentum': 0.9}})
    assert isinstance(c.optimizer_conf, SGDConf), type(c.optimizer_conf)
    assert c.optimizer_conf.lr.value() == 0.5
    assert c.optimizer_conf.momentum.value() == 0.9


@case
def behaviour_round_trip():
    c = TrainConf.from_dict({'optimizer_type': 'sgd', 'optimizer_conf': {'lr': 0.5}})
    again = TrainConf.from_dict(c.to_dict())
    assert again.to_dict() == c.to_dict()


@case
def behaviour_list_resize_by_monitor():
    d = DataConf.from_dict({'num_paths': 3, 'paths': ['x', 'y', 'z']})
    assert [p.value() for p in d.paths] == ['x', 'y', 'z']


@case
def behaviour_defaults_when_absent():
    c = TrainConf.from_dict({'epochs': 7})
    assert c.epochs.value() == 7
    assert c.optimizer_conf.lr.value() == 0.001      # adam default


@case
def behaviour_strict_catches_top_level_typo():
    try:
        TrainConf.from_dict({'epochsss': 7}, strict=True)
    except ValueError:
        return
    raise AssertionError('strict did not reject an unknown top-level field')


# --------------------------------------------------------------------------
# DEFECTS
# --------------------------------------------------------------------------

@case
def defect_S1_nested_block_dropped_when_trigger_omitted():
    """Omitting a field that merely equals its default must not delete a whole
    nested block. `optimizer_type` defaults to 'adam'; the monitor that swaps
    in AdamConf only runs on __setattr__, so with the trigger absent the
    nested conf stays a bare Conf and every key under it is discarded."""
    c = TrainConf.from_dict({'optimizer_conf': {'lr': 0.5, 'beta1': 0.8}})
    assert isinstance(c.optimizer_conf, AdamConf), \
        f'nested conf is {type(c.optimizer_conf).__name__}, values dropped'
    assert c.optimizer_conf.lr.value() == 0.5, 'lr silently reverted to default'


@case
def defect_S2_over_long_list_is_rejected():
    """A list longer than the declared count is silently truncated by zip()."""
    try:
        DataConf.from_dict({'num_paths': 2, 'paths': ['a', 'b', 'c']})
    except ValueError:
        return
    raise AssertionError('an over-long list was accepted and silently truncated')


@case
def defect_S3_parse_dict_does_not_mutate_class_defaults():
    class Holder(Conf):
        sub = SGDConf()

    Holder().parse_dict({'sub': {'lr': 0.999}})
    assert Holder().sub.lr.value() == 0.01, \
        'a fresh instance inherited a value parsed into another instance'
    assert Holder.sub.lr.value() == 0.01, 'the class default itself was rewritten'


@case
def defect_S4_strict_reaches_nested():
    try:
        TrainConf.from_dict(
            {'optimizer_type': 'sgd', 'optimizer_conf': {'lr': 0.5, 'momentuum': 0.9}},
            strict=True,
        )
    except ValueError:
        return
    raise AssertionError('strict did not reject a typo inside a nested conf')


@case
def defect_S5_option_named_none_is_selectable():
    a = OptionArg('adam', options=['adam', 'none', 'sgd'], allow_none=True)
    assert a.parse('none').value() == 'none', 'the option "none" became None'


@case
def defect_S5b_plain_string_none_survives():
    s = StrArg('x')
    assert s.parse('None').value() == 'None', '"None" was coerced to null'


@case
def defect_S6_boolarg_rejects_non_bool():
    for bad in (2, 3.7, [0], 'maybe'):
        try:
            BoolArg(False).parse(bad)
        except (ValueError, TypeError, AssertionError):
            continue
        raise AssertionError(f'BoolArg silently accepted {bad!r}')


@case
def defect_S6b_boolarg_accepts_on_off():
    assert BoolArg(False).parse('on').value() is True
    assert BoolArg(True).parse('off').value() is False


@case
def defect_S7_intarg_rejects_fractional():
    try:
        IntArg(1).parse(96.5)
    except (ValueError, TypeError):
        return
    raise AssertionError('IntArg silently truncated 96.5 to 96')


@case
def defect_S8_nan_rejected_by_bounds():
    try:
        FloatArg(0.5, min_value=0.0, max_value=1.0).parse(float('nan'))
    except ValueError:
        return
    raise AssertionError('NaN passed a min/max bounded FloatArg')


@case
def defect_S12_monitors_fire_once_per_parse():
    calls = []

    class Counted(Conf):
        n = IntArg(1)

        @monitor_on('n')
        def watch_n(self) -> None:
            calls.append(self.n.value())

    calls.clear()
    Counted.from_dict({'n': 5})
    assert calls.count(5) == 1, f'monitor fired {calls.count(5)}x for one parse: {calls}'


@case
def defect_S10_setattr_rejects_raw_value():
    c = TrainConf()
    try:
        c.epochs = 5            # forgot .parse() — replaces the IntArg
    except TypeError:
        return
    raise AssertionError('a raw value silently replaced an Arg field')


if __name__ == '__main__':
    print('BEHAVIOUR')
    behaviour_nested_parses_when_trigger_present()
    behaviour_round_trip()
    behaviour_list_resize_by_monitor()
    behaviour_defaults_when_absent()
    behaviour_strict_catches_top_level_typo()
    print('DEFECTS')
    defect_S1_nested_block_dropped_when_trigger_omitted()
    defect_S2_over_long_list_is_rejected()
    defect_S3_parse_dict_does_not_mutate_class_defaults()
    defect_S4_strict_reaches_nested()
    defect_S5_option_named_none_is_selectable()
    defect_S5b_plain_string_none_survives()
    defect_S6_boolarg_rejects_non_bool()
    defect_S6b_boolarg_accepts_on_off()
    defect_S7_intarg_rejects_fractional()
    defect_S8_nan_rejected_by_bounds()
    defect_S12_monitors_fire_once_per_parse()
    defect_S10_setattr_rejects_raw_value()
    print(f'\n{len(PASSED)} passed, {len(FAILED)} failed')
    for f in FAILED:
        print(f'  - {f}')
    sys.exit(1 if FAILED else 0)
