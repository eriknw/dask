from operator import getitem
from functools import partial

import pytest

from dask.utils_test import add, inc
from dask.core import get_dependencies
from dask.optimize import (cull, fuse, inline, inline_functions, functions_of,
                           fuse_getitem, fuse_selections, fuse_reductions)


def double(x):
    return x * 2


def test_cull():
    # 'out' depends on 'x' and 'y', but not 'z'
    d = {'x': 1, 'y': (inc, 'x'), 'z': (inc, 'x'), 'out': (add, 'y', 10)}
    culled, dependencies = cull(d, 'out')
    assert culled == {'x': 1, 'y': (inc, 'x'), 'out': (add, 'y', 10)}
    assert dependencies == {'x': [], 'y': ['x'], 'out': ['y']}

    assert cull(d, 'out') == cull(d, ['out'])
    assert cull(d, ['out', 'z'])[0] == d
    assert cull(d, [['out'], ['z']]) == cull(d, ['out', 'z'])
    pytest.raises(KeyError, lambda: cull(d, 'badkey'))


def fuse2(*args, **kwargs):
    """Run both `fuse` and `fuse_reductions` and compare results"""
    if kwargs.get('rename_fused_keys'):
        return fuse(*args, **kwargs)
    rv1 = fuse(*args, **kwargs)
    kwargs['ave_width'] = 1
    kwargs.pop('rename_fused_keys')
    rv2 = fuse_reductions(*args, **kwargs)
    assert rv1 == rv2
    return rv1


def with_deps(dsk):
    return dsk, {k: get_dependencies(dsk, k) for k in dsk}


def test_fuse():
    fuse = fuse2  # tests both `fuse` and `fuse_reductions`
    d = {
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2,
    }
    assert fuse(d, rename_fused_keys=False) == with_deps({
        'w': (inc, (inc, (inc, (add, 'a', 'b')))),
        'a': 1,
        'b': 2,
    })
    assert fuse(d, rename_fused_keys=True) == with_deps({
        'z-y-x-w': (inc, (inc, (inc, (add, 'a', 'b')))),
        'a': 1,
        'b': 2,
        'w': 'z-y-x-w',
    })

    d = {
        'NEW': (inc, 'y'),
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2,
    }
    assert fuse(d, rename_fused_keys=False) == with_deps({
        'NEW': (inc, 'y'),
        'w': (inc, (inc, 'y')),
        'y': (inc, (add, 'a', 'b')),
        'a': 1,
        'b': 2,
    })
    assert fuse(d, rename_fused_keys=True) == with_deps({
        'NEW': (inc, 'z-y'),
        'x-w': (inc, (inc, 'z-y')),
        'z-y': (inc, (add, 'a', 'b')),
        'a': 1,
        'b': 2,
        'w': 'x-w',
        'y': 'z-y',
    })

    d = {
        'v': (inc, 'y'),
        'u': (inc, 'w'),
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': (inc, 'c'),
        'b': (inc, 'd'),
        'c': 1,
        'd': 2,
    }
    assert fuse(d, rename_fused_keys=False) == with_deps({
        'u': (inc, (inc, (inc, 'y'))),
        'v': (inc, 'y'),
        'y': (inc, (add, 'a', 'b')),
        'a': (inc, 1),
        'b': (inc, 2),
    })
    assert fuse(d, rename_fused_keys=True) == with_deps({
        'x-w-u': (inc, (inc, (inc, 'z-y'))),
        'v': (inc, 'z-y'),
        'z-y': (inc, (add, 'c-a', 'd-b')),
        'c-a': (inc, 1),
        'd-b': (inc, 2),
        'a': 'c-a',
        'b': 'd-b',
        'u': 'x-w-u',
        'y': 'z-y',
    })

    d = {
        'a': (inc, 'x'),
        'b': (inc, 'x'),
        'c': (inc, 'x'),
        'd': (inc, 'c'),
        'x': (inc, 'y'),
        'y': 0,
    }
    assert fuse(d, rename_fused_keys=False) == with_deps({
        'a': (inc, 'x'),
        'b': (inc, 'x'),
        'd': (inc, (inc, 'x')),
        'x': (inc, 0)
    })
    assert fuse(d, rename_fused_keys=True) == with_deps({
        'a': (inc, 'y-x'),
        'b': (inc, 'y-x'),
        'c-d': (inc, (inc, 'y-x')),
        'y-x': (inc, 0),
        'd': 'c-d',
        'x': 'y-x',
    })

    d = {
        'a': 1,
        'b': (inc, 'a'),
        'c': (add, 'b', 'b'),
    }
    assert fuse(d, rename_fused_keys=False) == with_deps({
        'b': (inc, 1),
        'c': (add, 'b', 'b'),
    })
    assert fuse(d, rename_fused_keys=True) == with_deps({
        'a-b': (inc, 1),
        'c': (add, 'a-b', 'a-b'),
        'b': 'a-b',
    })


def test_fuse_keys():
    fuse = fuse2  # tests both `fuse` and `fuse_reductions`
    d = {
        'a': 1,
        'b': (inc, 'a'),
        'c': (inc, 'b'),
    }
    keys = ['b']
    assert fuse(d, keys, rename_fused_keys=False) == with_deps({
        'b': (inc, 1),
        'c': (inc, 'b'),
    })
    assert fuse(d, keys, rename_fused_keys=True) == with_deps({
        'a-b': (inc, 1),
        'c': (inc, 'a-b'),
        'b': 'a-b',
    })

    d = {
        'w': (inc, 'x'),
        'x': (inc, 'y'),
        'y': (inc, 'z'),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2,
    }
    keys = ['x', 'z']
    assert fuse(d, keys, rename_fused_keys=False) == with_deps({
        'w': (inc, 'x'),
        'x': (inc, (inc, 'z')),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2 ,
    })
    assert fuse(d, keys, rename_fused_keys=True) == with_deps({
        'w': (inc, 'y-x'),
        'y-x': (inc, (inc, 'z')),
        'z': (add, 'a', 'b'),
        'a': 1,
        'b': 2 ,
        'x': 'y-x',
    })


def test_inline():
    d = {'a': 1,
         'b': (inc, 'a'),
         'c': (inc, 'b'),
         'd': (add, 'a', 'c')}
    assert inline(d) == {'a': 1,
                         'b': (inc, 1),
                         'c': (inc, 'b'),
                         'd': (add, 1, 'c')}
    assert inline(d, ['a', 'b', 'c']) == {'a': 1,
                                          'b': (inc, 1),
                                          'c': (inc, (inc, 1)),
                                          'd': (add, 1, (inc, (inc, 1)))}
    d = {'x': 1,
         'y': (inc, 'x'),
         'z': (add, 'x', 'y')}
    assert inline(d) == {'x': 1,
                         'y': (inc, 1),
                         'z': (add, 1, 'y')}
    assert inline(d, keys='y') == {'x': 1,
                                   'y': (inc, 1),
                                   'z': (add, 1, (inc, 1))}
    assert inline(d, keys='y',
                  inline_constants=False) == {'x': 1,
                                              'y': (inc, 'x'),
                                              'z': (add, 'x', (inc, 'x'))}

    d = {'a': 1,
         'b': 'a',
         'c': 'b',
         'd': ['a', 'b', 'c'],
         'e': (add, (len, 'd'), 'a')}
    assert inline(d, 'd') == {'a': 1,
                              'b': 1,
                              'c': 1,
                              'd': [1, 1, 1],
                              'e': (add, (len, [1, 1, 1]), 1)}
    assert inline(d, 'a',
                  inline_constants=False) == {'a': 1,
                                              'b': 1,
                                              'c': 'b',
                                              'd': [1, 'b', 'c'],
                                              'e': (add, (len, 'd'), 1)}


def test_inline_functions():
    x, y, i, d = 'xyid'
    dsk = {'out': (add, i, d),
           i: (inc, x),
           d: (double, y),
           x: 1, y: 1}

    result = inline_functions(dsk, [], fast_functions=set([inc]))
    expected = {'out': (add, (inc, x), d),
                d: (double, y),
                x: 1, y: 1}
    assert result == expected


def test_inline_ignores_curries_and_partials():
    dsk = {'x': 1, 'y': 2,
           'a': (partial(add, 1), 'x'),
           'b': (inc, 'a')}

    result = inline_functions(dsk, [], fast_functions=set([add]))
    assert result['b'] == (inc, dsk['a'])
    assert 'a' not in result


def test_inline_doesnt_shrink_fast_functions_at_top():
    dsk = {'x': (inc, 'y'), 'y': 1}
    result = inline_functions(dsk, [], fast_functions=set([inc]))
    assert result == dsk


def test_inline_traverses_lists():
    x, y, i, d = 'xyid'
    dsk = {'out': (sum, [i, d]),
           i: (inc, x),
           d: (double, y),
           x: 1, y: 1}
    expected = {'out': (sum, [(inc, x), d]),
                d: (double, y),
                x: 1, y: 1}
    result = inline_functions(dsk, [], fast_functions=set([inc]))
    assert result == expected


def test_inline_functions_protects_output_keys():
    dsk = {'x': (inc, 1), 'y': (double, 'x')}
    assert inline_functions(dsk, [], [inc]) == {'y': (double, (inc, 1))}
    assert inline_functions(dsk, ['x'], [inc]) == {'y': (double, 'x'),
                                                   'x': (inc, 1)}


def test_functions_of():
    a = lambda x: x
    b = lambda x: x
    assert functions_of((a, 1)) == set([a])
    assert functions_of((a, (b, 1))) == set([a, b])
    assert functions_of((a, [(b, 1)])) == set([a, b])
    assert functions_of((a, [[[(b, 1)]]])) == set([a, b])
    assert functions_of(1) == set()
    assert functions_of(a) == set()
    assert functions_of((a,)) == set([a])


def test_fuse_getitem():
    def load(*args):
        pass
    dsk = {'x': (load, 'store', 'part', ['a', 'b']),
           'y': (getitem, 'x', 'a')}
    dsk2 = fuse_getitem(dsk, load, 3)
    dsk2, dependencies = cull(dsk2, 'y')
    assert dsk2 == {'y': (load, 'store', 'part', 'a')}


def test_fuse_selections():
    def load(*args):
        pass
    dsk = {'x': (load, 'store', 'part', ['a', 'b']),
           'y': (getitem, 'x', 'a')}
    merge = lambda t1, t2: (load, t2[1], t2[2], t1[2])
    dsk2 = fuse_selections(dsk, getitem, load, merge)
    dsk2, dependencies = cull(dsk2, 'y')
    assert dsk2 == {'y': (load, 'store', 'part', 'a')}


def test_inline_cull_dependencies():
    d = {'a': 1,
         'b': 'a',
         'c': 'b',
         'd': ['a', 'b', 'c'],
         'e': (add, (len, 'd'), 'a')}

    d2, dependencies = cull(d, ['d', 'e'])
    inline(d2, {'b'}, dependencies=dependencies)


def test_fuse_reductions_single_input():
    def f(*args):
        return args

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a', 'a'),
        'c': (f, 'b1', 'b2'),
    }
    assert fuse_reductions(d, ave_width=1.9) == with_deps(d)
    assert fuse_reductions(d, ave_width=2) == with_deps({
        'a': 1,
        'c': (f, (f, 'a'), (f, 'a', 'a')),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a', 'a'),
        'b3': (f, 'a', 'a', 'a'),
        'c': (f, 'b1', 'b2', 'b3'),
    }
    assert fuse_reductions(d, ave_width=2.9) == with_deps(d)
    assert fuse_reductions(d, ave_width=3) == with_deps({
        'a': 1,
        'c': (f, (f, 'a'), (f, 'a', 'a'), (f, 'a', 'a', 'a')),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'c': (f, 'a', 'b1', 'b2'),
    }
    assert fuse_reductions(d, ave_width=1.9) == with_deps(d)
    assert fuse_reductions(d, ave_width=2) == with_deps({
        'a': 1,
        'c': (f, 'a', (f, 'a'), (f, 'a')),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'c': (f, 'b1', 'b2'),
        'd1': (f, 'c'),
        'd2': (f, 'c'),
        'e': (f, 'd1', 'd2'),
    }
    assert fuse_reductions(d, ave_width=1.9) == with_deps(d)
    assert fuse_reductions(d, ave_width=2) == with_deps({
        'a': 1,
        'c': (f, (f, 'a'), (f, 'a')),
        'e': (f, (f, 'c'), (f, 'c')),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'b3': (f, 'a'),
        'b4': (f, 'a'),
        'c1': (f, 'b1', 'b2'),
        'c2': (f, 'b3', 'b4'),
        'd': (f, 'c1', 'c2'),
    }
    assert fuse_reductions(d, ave_width=1.9) == with_deps(d)
    expected = with_deps({
        'a': 1,
        'c1': (f, (f, 'a'), (f, 'a')),
        'c2': (f, (f, 'a'), (f, 'a')),
        'd': (f, 'c1', 'c2'),
    })
    assert fuse_reductions(d, ave_width=2) == expected
    assert fuse_reductions(d, ave_width=2.9) == expected
    assert fuse_reductions(d, ave_width=3) == with_deps({
        'a': 1,
        'd': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'b3': (f, 'a'),
        'b4': (f, 'a'),
        'b5': (f, 'a'),
        'b6': (f, 'a'),
        'b7': (f, 'a'),
        'b8': (f, 'a'),
        'c1': (f, 'b1', 'b2'),
        'c2': (f, 'b3', 'b4'),
        'c3': (f, 'b5', 'b6'),
        'c4': (f, 'b7', 'b8'),
        'd1': (f, 'c1', 'c2'),
        'd2': (f, 'c3', 'c4'),
        'e': (f, 'd1', 'd2'),
    }
    assert fuse_reductions(d, ave_width=1.9) == with_deps(d)
    expected = with_deps({
        'a': 1,
        'c1': (f, (f, 'a'), (f, 'a')),
        'c2': (f, (f, 'a'), (f, 'a')),
        'c3': (f, (f, 'a'), (f, 'a')),
        'c4': (f, (f, 'a'), (f, 'a')),
        'd1': (f, 'c1', 'c2'),
        'd2': (f, 'c3', 'c4'),
        'e': (f, 'd1', 'd2'),
    })
    assert fuse_reductions(d, ave_width=2) == expected
    assert fuse_reductions(d, ave_width=2.9) == expected
    expected = with_deps({
        'a': 1,
        'd1': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
        'd2': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
        'e': (f, 'd1', 'd2'),
    })
    assert fuse_reductions(d, ave_width=3) == expected
    assert fuse_reductions(d, ave_width=4.6) == expected
    assert fuse_reductions(d, ave_width=4.7) == with_deps({
        'a': 1,
        'e': (f, (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
              (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))))
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'b3': (f, 'a'),
        'b4': (f, 'a'),
        'b5': (f, 'a'),
        'b6': (f, 'a'),
        'b7': (f, 'a'),
        'b8': (f, 'a'),
        'b9': (f, 'a'),
        'b10': (f, 'a'),
        'b11': (f, 'a'),
        'b12': (f, 'a'),
        'b13': (f, 'a'),
        'b14': (f, 'a'),
        'b15': (f, 'a'),
        'b16': (f, 'a'),
        'c1': (f, 'b1', 'b2'),
        'c2': (f, 'b3', 'b4'),
        'c3': (f, 'b5', 'b6'),
        'c4': (f, 'b7', 'b8'),
        'c5': (f, 'b9', 'b10'),
        'c6': (f, 'b11', 'b12'),
        'c7': (f, 'b13', 'b14'),
        'c8': (f, 'b15', 'b16'),
        'd1': (f, 'c1', 'c2'),
        'd2': (f, 'c3', 'c4'),
        'd3': (f, 'c5', 'c6'),
        'd4': (f, 'c7', 'c8'),
        'e1': (f, 'd1', 'd2'),
        'e2': (f, 'd3', 'd4'),
        'f': (f, 'e1', 'e2'),
    }
    assert fuse_reductions(d, ave_width=1.9) == with_deps(d)
    expected = with_deps({
        'a': 1,
        'c1': (f, (f, 'a'), (f, 'a')),
        'c2': (f, (f, 'a'), (f, 'a')),
        'c3': (f, (f, 'a'), (f, 'a')),
        'c4': (f, (f, 'a'), (f, 'a')),
        'c5': (f, (f, 'a'), (f, 'a')),
        'c6': (f, (f, 'a'), (f, 'a')),
        'c7': (f, (f, 'a'), (f, 'a')),
        'c8': (f, (f, 'a'), (f, 'a')),
        'd1': (f, 'c1', 'c2'),
        'd2': (f, 'c3', 'c4'),
        'd3': (f, 'c5', 'c6'),
        'd4': (f, 'c7', 'c8'),
        'e1': (f, 'd1', 'd2'),
        'e2': (f, 'd3', 'd4'),
        'f': (f, 'e1', 'e2'),
    })
    assert fuse_reductions(d, ave_width=2) == expected
    assert fuse_reductions(d, ave_width=2.9) == expected
    expected = with_deps({
        'a': 1,
        'd1': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
        'd2': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
        'd3': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
        'd4': (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
        'e1': (f, 'd1', 'd2'),
        'e2': (f, 'd3', 'd4'),
        'f': (f, 'e1', 'e2'),
    })
    assert fuse_reductions(d, ave_width=3) == expected
    assert fuse_reductions(d, ave_width=4.6) == expected
    expected = with_deps({
        'a': 1,
        'e1': (f, (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
               (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a')))),
        'e2': (f, (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
               (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a')))),
        'f': (f, 'e1', 'e2'),
    })
    assert fuse_reductions(d, ave_width=4.7) == expected
    assert fuse_reductions(d, ave_width=7.4) == expected
    assert fuse_reductions(d, ave_width=7.5) == with_deps({
        'a': 1,
        'f': (f, (f, (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
                  (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a')))),
              (f, (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))),
               (f, (f, (f, 'a'), (f, 'a')), (f, (f, 'a'), (f, 'a'))))),
    })

    d = {
        'a': 1,
        'b': (f, 'a'),
    }
    assert fuse_reductions(d, ave_width=1) == with_deps({
        'b': (f, 1)
    })

    d = {
        'a': 1,
        'b': (f, 'a'),
        'c': (f, 'b'),
        'd': (f, 'c'),
    }
    assert fuse_reductions(d, ave_width=1) == with_deps({
        'd': (f, (f, (f, 1)))
    })

    d = {
        'a': 1,
        'b': (f, 'a'),
        'c': (f, 'a', 'b'),
        'd': (f, 'a', 'c'),
    }
    assert fuse_reductions(d, ave_width=1) == with_deps({
        'a': 1,
        'd': (f, 'a', (f, 'a', (f, 'a'))),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'c1': (f, 'b1'),
        'd1': (f, 'c1'),
        'e1': (f, 'd1'),
        'f': (f, 'e1', 'b2'),
    }
    expected = with_deps({
        'a': 1,
        'b2': (f, 'a'),
        'e1': (f, (f, (f, (f, 'a')))),
        'f': (f, 'e1', 'b2'),

    })
    assert fuse_reductions(d, ave_width=1) == expected
    assert fuse_reductions(d, ave_width=1.9) == expected
    assert fuse_reductions(d, ave_width=2) == with_deps({
        'a': 1,
        'f': (f, (f, (f, (f, (f, 'a')))), (f, 'a')),
    })

    d = {
        'a': 1,
        'b1': (f, 'a'),
        'b2': (f, 'a'),
        'c1': (f, 'a', 'b1'),
        'd1': (f, 'a', 'c1'),
        'e1': (f, 'a', 'd1'),
        'f': (f, 'a', 'e1', 'b2'),
    }
    expected = with_deps({
        'a': 1,
        'b2': (f, 'a'),
        'e1': (f, 'a', (f, 'a', (f, 'a', (f, 'a')))),
        'f': (f, 'a', 'e1', 'b2'),

    })
    assert fuse_reductions(d, ave_width=1) == expected
    assert fuse_reductions(d, ave_width=1.9) == expected
    assert fuse_reductions(d, ave_width=2) == with_deps({
        'a': 1,
        'f': (f, 'a', (f, 'a', (f, 'a', (f, 'a', (f, 'a')))), (f, 'a')),
    })


def test_fuse_reductions_multiple_input():
    def f(*args):
        return args

    d = {
        'a1': 1,
        'a2': 2,
        'b': (f, 'a1', 'a2'),
        'c': (f, 'b'),
    }
    assert fuse_reductions(d, ave_width=2) == with_deps({'c': (f, (f, 1, 2))})
    assert fuse_reductions(d, ave_width=1) == with_deps({
        'a1': 1,
        'a2': 2,
        'c': (f, (f, 'a1', 'a2')),
    })

    d = {
        'a1': 1,
        'a2': 2,
        'b1': (f, 'a1'),
        'b2': (f, 'a1', 'a2'),
        'b3': (f, 'a2'),
        'c': (f, 'b1', 'b2', 'b3'),
    }
    expected = with_deps(d)
    assert fuse_reductions(d, ave_width=1) == expected
    assert fuse_reductions(d, ave_width=2.9) == expected
    assert fuse_reductions(d, ave_width=3) == with_deps({
        'a1': 1,
        'a2': 2,
        'c': (f, (f, 'a1'), (f, 'a1', 'a2'), (f, 'a2')),
    })

    d = {
        'a1': 1,
        'a2': 2,
        'b1': (f, 'a1'),
        'b2': (f, 'a1', 'a2'),
        'b3': (f, 'a2'),
        'c1': (f, 'b1', 'b2'),
        'c2': (f, 'b2', 'b3'),
    }
    assert fuse_reductions(d, ave_width=1) == with_deps(d)
    assert fuse_reductions(d, ave_width=2) == with_deps({
        'a1': 1,
        'a2': 2,
        'b2': (f, 'a1', 'a2'),
        'c1': (f, (f, 'a1'), 'b2'),
        'c2': (f, 'b2', (f, 'a2')),
    })

    d = {
        'a1': 1,
        'a2': 2,
        'b1': (f, 'a1'),
        'b2': (f, 'a1', 'a2'),
        'b3': (f, 'a2'),
        'c1': (f, 'b1', 'b2'),
        'c2': (f, 'b2', 'b3'),
        'd': (f, 'c1', 'c2'),
    }
    assert fuse_reductions(d, ave_width=1) == with_deps(d)

    # A more aggressive heuristic could do this at `ave_width=2`.  Perhaps
    # we can improve this.  Nevertheless, this is behaving as intended.
    assert fuse_reductions(d, ave_width=3) == with_deps({
        'a1': 1,
        'a2': 2,
        'b2': (f, 'a1', 'a2'),
        'd': (f, (f, (f, 'a1'), 'b2'), (f, 'b2', (f, 'a2'))),
    })
