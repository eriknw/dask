import dask
from dask.array import *
from toolz import merge

def contains(a, b):
    """

    >>> contains({'x': 1, 'y': 2}, {'x': 1})
    True
    >>> contains({'x': 1, 'y': 2}, {'z': 3})
    False
    """
    return all(a.get(k) == v for k, v in b.items())


def test_getem():
    assert getem('X', blocksize=(2, 3), shape=(4, 6)) == \
    {('X', 0, 0): (operator.getitem, 'X', (slice(0, 2), slice(0, 3))),
     ('X', 1, 0): (operator.getitem, 'X', (slice(2, 4), slice(0, 3))),
     ('X', 1, 1): (operator.getitem, 'X', (slice(2, 4), slice(3, 6))),
     ('X', 0, 1): (operator.getitem, 'X', (slice(0, 2), slice(3, 6)))}

inc = lambda x: x + 1
add = lambda x, y: x + y


def test_top():
    assert top(inc, 'z', 'ij', 'x', 'ij', numblocks={'x': (2, 2)}) == \
        {('z', 0, 0): (inc, ('x', 0, 0)),
         ('z', 0, 1): (inc, ('x', 0, 1)),
         ('z', 1, 0): (inc, ('x', 1, 0)),
         ('z', 1, 1): (inc, ('x', 1, 1))}

    assert top(add, 'z', 'ij', 'x', 'ij', 'y', 'ij',
                numblocks={'x': (2, 2), 'y': (2, 2)}) == \
        {('z', 0, 0): (add, ('x', 0, 0), ('y', 0, 0)),
         ('z', 0, 1): (add, ('x', 0, 1), ('y', 0, 1)),
         ('z', 1, 0): (add, ('x', 1, 0), ('y', 1, 0)),
         ('z', 1, 1): (add, ('x', 1, 1), ('y', 1, 1))}

    assert top(dotmany, 'z', 'ik', 'x', 'ij', 'y', 'jk',
                    numblocks={'x': (2, 2), 'y': (2, 2)}) == \
        {('z', 0, 0): (dotmany, [('x', 0, 0), ('x', 0, 1)],
                                [('y', 0, 0), ('y', 1, 0)]),
         ('z', 0, 1): (dotmany, [('x', 0, 0), ('x', 0, 1)],
                                [('y', 0, 1), ('y', 1, 1)]),
         ('z', 1, 0): (dotmany, [('x', 1, 0), ('x', 1, 1)],
                                [('y', 0, 0), ('y', 1, 0)]),
         ('z', 1, 1): (dotmany, [('x', 1, 0), ('x', 1, 1)],
                                [('y', 0, 1), ('y', 1, 1)])}

    assert top(identity, 'z', '', 'x', 'ij', numblocks={'x': (2, 2)}) ==\
        {('z',): (identity, [[('x', 0, 0), ('x', 0, 1)],
                             [('x', 1, 0), ('x', 1, 1)]])}


def test_top_supports_broadcasting_rules():
    assert top(add, 'z', 'ij', 'x', 'ij', 'y', 'ij',
                numblocks={'x': (1, 2), 'y': (2, 1)}) == \
        {('z', 0, 0): (add, ('x', 0, 0), ('y', 0, 0)),
         ('z', 0, 1): (add, ('x', 0, 1), ('y', 0, 0)),
         ('z', 1, 0): (add, ('x', 0, 0), ('y', 1, 0)),
         ('z', 1, 1): (add, ('x', 0, 1), ('y', 1, 0))}


def test_concatenate():
    x = np.array([1, 2])
    assert concatenate([[x, x, x], [x, x, x]]).shape == (2, 6)

    x = np.array([[1, 2]])
    assert concatenate([[x, x, x], [x, x, x]]).shape == (2, 6)


def eq(a, b):
    c = a == b
    if isinstance(c, np.ndarray):
        c = c.all()
    return c


def test_chunked_dot_product():
    x = np.arange(400).reshape((20, 20))
    o = np.ones((20, 20))

    d = {'x': x, 'o': o}

    getx = getem('x', (5, 5), (20, 20))
    geto = getem('o', (5, 5), (20, 20))

    result = top(dotmany, 'out', 'ik', 'x', 'ij', 'o', 'jk',
                 numblocks={'x': (4, 4), 'o': (4, 4)})

    dsk = merge(d, getx, geto, result)
    out = dask.get(dsk, [[('out', i, j) for j in range(4)] for i in range(4)])

    assert eq(np.dot(x, o), concatenate(out))


def test_chunked_transpose_plus_one():
    x = np.arange(400).reshape((20, 20))

    d = {'x': x}

    getx = getem('x', (5, 5), (20, 20))

    f = lambda x: x.T + 1
    comp = top(f, 'out', 'ij', 'x', 'ji', numblocks={'x': (4, 4)})

    dsk = merge(d, getx, comp)
    out = dask.get(dsk, [[('out', i, j) for j in range(4)] for i in range(4)])

    assert eq(concatenate(out), x.T + 1)
