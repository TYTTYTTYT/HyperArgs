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


# --------------------------------------------------------------------------
# REGRESSIONS — found by adversarial review of the first attempt at these
# fixes. Each one passed on 0.1.3 and broke on the first draft of 0.1.4.
# --------------------------------------------------------------------------

class Wide(Conf):
    paths = [StrArg('a'), StrArg('b'), StrArg('c')]


@add_dependency('conf', 'kind')          # deliberately BACKWARDS, as in the wild
class Selector(Conf):
    kind = OptionArg('narrow', options=['narrow', 'wide'])
    conf = Conf()

    @monitor_on('kind')
    def swap(self) -> None:
        want = Wide if self.kind.value() == 'wide' else Conf
        if self.conf.__class__ is not want:
            self.conf = want()


@add_dependency('derived', 'source')     # also backwards, as the README's example
class Derived(Conf):
    source = IntArg(1)
    derived = IntArg(2)

    @monitor_on('source')
    def recompute(self) -> None:
        self.derived = self.derived.parse(self.source.value() * 2)


@case
def regression_derived_field_not_overridden_by_stale_file_value():
    """A monitor that computes one field from another must win over whatever
    the file carries — configs are written back out with the derived value in
    them, so a stale copy is present in every saved config."""
    c = Derived.from_dict({'source': 8, 'derived': 10})
    assert c.derived.value() == 16, \
        f'stale file value won over the monitor ({c.derived.value()})'


@case
def regression_nested_parsed_against_the_real_subclass():
    """With the dependency declared backwards, the nested block must still be
    parsed against the subclass the monitor selects — not against the
    placeholder that happens to come first in declaration order."""
    c = Selector.from_dict({'kind': 'wide', 'conf': {'paths': ['x', 'y', 'z']}})
    assert isinstance(c.conf, Wide), type(c.conf).__name__
    assert [p.value() for p in c.conf.paths] == ['x', 'y', 'z']


@case
def regression_strict_with_backwards_dependency():
    """strict must not flag the real subclass's own fields as unexpected."""
    Selector.from_dict({'kind': 'wide', 'conf': {'paths': ['x', 'y', 'z']}}, strict=True)


@case
def regression_monitor_failure_is_not_fatal_at_construction():
    """Firing monitors to materialize defaults must not make a class with a
    fragile monitor unconstructible."""
    class Boom(Conf):
        y = IntArg(1)

        @monitor_on('y')
        def explode(self) -> None:
            raise RuntimeError('monitor exploded')

    Boom()                       # must not raise
    # assignment is a different matter: a monitor that fails when the field it
    # watches actually changes is a real error and still propagates, as it did
    # before defaults were materialized at construction
    try:
        Boom.from_dict({'y': 5})
    except RuntimeError:
        return
    raise AssertionError('a monitor failure on assignment was swallowed')


@case
def regression_tuple_field_accepted():
    """The parse path accepts tuples, so __setattr__ must too."""
    class T(Conf):
        pair = [StrArg('a'), StrArg('b')]

    t = T()
    t.pair = (StrArg('x'), StrArg('y'))      # must not raise


# --------------------------------------------------------------------------
# ROUND 3 — monitors whose TRIGGER is a container, and monitors that CONFIGURE
# a nested block rather than choosing its class. Both were broken by the
# scalars-then-containers ordering; neither had a test.
# --------------------------------------------------------------------------

class Block(Conf):
    n = IntArg(1)
    m = IntArg(2)


@add_dependency('mode', 'block')
class Configures(Conf):
    mode = OptionArg('fast', options=['fast', 'slow'])
    block = Block()

    @monitor_on('mode')
    def tune(self) -> None:
        if self.mode.value() == 'slow':
            self.block.n = self.block.n.parse(200)


@add_dependency('inner', 'outer')        # backwards, and BOTH are containers
class ContainerTrigger(Conf):
    outer = Block()
    inner = Conf()

    @monitor_on('outer')
    def swap_inner(self) -> None:
        want = Wide if self.outer.n.value() >= 5 else Conf
        if self.inner.__class__ is not want:
            self.inner = want()


@add_dependency('block', 'n_items')
class ContainerSetsScalar(Conf):
    block = Block()
    n_items = IntArg(0)

    @monitor_on('block')
    def sync(self) -> None:
        self.n_items = self.n_items.parse(self.block.n.value())


@case
def regression_monitor_configured_nested_values_survive():
    """A monitor that CONFIGURES a nested block (rather than choosing its
    class) must not lose that configuration the moment the file mentions the
    block. _parse_attr used from_dict — a classmethod — which built a fresh
    instance and discarded everything the monitor had set."""
    c = Configures.from_dict({'mode': 'slow', 'block': {'m': 42}})
    assert c.block.m.value() == 42, 'file value lost'
    assert c.block.n.value() == 200, \
        f'monitor-set value in the nested block was discarded (n={c.block.n.value()})'


@case
def regression_container_triggered_monitor_rebuilding_a_container():
    """The trigger is itself a container, so 'scalars first' gives no ordering
    at all; the victim must still end up with the file's values."""
    c = ContainerTrigger.from_dict({'outer': {'n': 5}, 'inner': {'paths': ['x', 'y', 'z']}})
    assert isinstance(c.inner, Wide), type(c.inner).__name__
    assert [p.value() for p in c.inner.paths] == ['x', 'y', 'z'], \
        'file values for the rebuilt container were dropped'


@case
def regression_container_triggered_monitor_does_not_clobber_a_scalar():
    """With the dependency declared correctly (block -> n_items), the file's
    explicit n_items must win, exactly as it did before."""
    c = ContainerSetsScalar.from_dict({'block': {'n': 7}, 'n_items': 99})
    assert c.n_items.value() == 99, \
        f'a container-triggered monitor overwrote an explicit file value ({c.n_items.value()})'


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
    print('REGRESSIONS')
    regression_derived_field_not_overridden_by_stale_file_value()
    regression_nested_parsed_against_the_real_subclass()
    regression_strict_with_backwards_dependency()
    regression_monitor_failure_is_not_fatal_at_construction()
    regression_tuple_field_accepted()
    regression_monitor_configured_nested_values_survive()
    regression_container_triggered_monitor_rebuilding_a_container()
    regression_container_triggered_monitor_does_not_clobber_a_scalar()
    print(f'\n{len(PASSED)} passed, {len(FAILED)} failed')
    for f in FAILED:
        print(f'  - {f}')
    sys.exit(1 if FAILED else 0)
