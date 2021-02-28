from dataclasses import dataclass, replace
from typing import Tuple, Type, Union, Optional, Dict, Callable
from collections import namedtuple

import numpy as np
from numpy import ndarray

from ..element import (Element, ElementHex1, ElementQuad1, ElementQuad2,
                       ElementTetP1, ElementTriP1, ElementTriP2,
                       BOUNDARY_ELEMENT_MAP)


@dataclass
class BaseMesh:

    doflocs: ndarray
    t: ndarray
    elem: Type[Element] = Element
    affine: bool = False
    validate: bool = False  # for backwards compatibility

    @property
    def p(self):
        return self.doflocs

    @property
    def dofs(self):
        from skfem.assembly import Dofs
        if not hasattr(self, '_dofs'):
            self._dofs = Dofs(self, self.elem())
        return self._dofs

    @property
    def refdom(self):
        return self.elem.refdom

    @property
    def brefdom(self):
        return self.elem.refdom.brefdom

    @property
    def bndelem(self):
        return BOUNDARY_ELEMENT_MAP[self.elem]()

    @property
    def nelements(self):
        return self.t.shape[1]

    @property
    def nvertices(self):
        return np.max(self.t) + 1

    @property
    def nfacets(self):
        return self.facets.shape[1]

    @property
    def nedges(self):
        return self.edges.shape[1]

    @property
    def nnodes(self):
        return self.t.shape[0]

    @property
    def subdomains(self):
        return None

    @property
    def boundaries(self):
        return None

    @property
    def facets(self):
        if not hasattr(self, '_facets'):
            self._init_facets()
        return self._facets

    @property
    def t2f(self):
        if not hasattr(self, '_t2f'):
            self._init_facets()
        return self._t2f

    @property
    def f2t(self):
        if not hasattr(self, '_f2t'):
            self._f2t = self.build_inverse(self.t, self.t2f)
        return self._f2t

    @property
    def edges(self):
        if not hasattr(self, '_edges'):
            self._init_edges()
        return self._edges

    @property
    def t2e(self):
        if not hasattr(self, '_t2e'):
            self._init_edges()
        return self._t2e

    def dim(self):
        return self.elem.refdom.dim()

    def boundary_facets(self) -> ndarray:
        """Return an array of boundary facet indices."""
        return np.nonzero(self.f2t[1] == -1)[0]

    def boundary_edges(self) -> ndarray:
        """Return an array of boundary edge indices."""
        facets = self.boundary_facets()
        boundary_edges = np.sort(np.hstack(
            tuple([np.vstack((self.facets[itr, facets],
                              self.facets[(itr + 1) % self.facets.shape[0],
                              facets]))
                   for itr in range(self.facets.shape[0])])).T, axis=1)
        edge_candidates = np.unique(self.t2e[:, self.f2t[0, facets]])
        A = self.edges[:, edge_candidates].T
        B = boundary_edges
        dims = A.max(0) + 1
        ix = np.where(np.in1d(np.ravel_multi_index(A.T, dims),
                              np.ravel_multi_index(B.T, dims)))[0]
        return edge_candidates[ix]

    def boundary_nodes(self) -> ndarray:
        """Return an array of boundary node indices."""
        return np.unique(self.facets[:, self.boundary_facets()])

    def interior_nodes(self) -> ndarray:
        """Return an array of interior node indices."""
        return np.setdiff1d(np.arange(0, self.p.shape[1]),
                            self.boundary_nodes())

    def nodes_satisfying(self,
                         test: Callable[[ndarray], ndarray],
                         boundaries_only: bool = False) -> ndarray:
        """Return nodes that satisfy some condition.

        Parameters
        ----------
        test
            A function which returns True for the set of nodes that are to be
            included in the return set.
        boundaries_only
            If True, include only boundary facets.

        """
        nodes = np.nonzero(test(self.p))[0]
        if boundaries_only:
            nodes = np.intersect1d(nodes, self.boundary_nodes())
        return nodes

    def facets_satisfying(self,
                          test: Callable[[ndarray], ndarray],
                          boundaries_only: bool = False) -> ndarray:
        """Return facets whose midpoints satisfy some condition.

        Parameters
        ----------
        test
            A function which returns ``True`` for the facet midpoints that are
            to be included in the return set.
        boundaries_only
            If ``True``, include only boundary facets.

        """
        midp = [np.sum(self.p[itr, self.facets], axis=0) / self.facets.shape[0]
                for itr in range(self.dim())]
        facets = np.nonzero(test(np.array(midp)))[0]
        if boundaries_only:
            facets = np.intersect1d(facets, self.boundary_facets())
        return facets

    def elements_satisfying(self,
                            test: Callable[[ndarray], ndarray]) -> ndarray:
        """Return elements whose midpoints satisfy some condition.

        Parameters
        ----------
        test
            A function which returns ``True`` for the element midpoints that
            are to be included in the return set.

        """
        midp = [np.sum(self.p[itr, self.t], axis=0) / self.t.shape[0]
                for itr in range(self.dim())]
        return np.nonzero(test(np.array(midp)))[0]

    def _expand_facets(self, ix: ndarray) -> Tuple[ndarray, ndarray]:
        """Return vertices and edges corresponding to given facet indices.

        Parameters
        ----------
        ix
            An array of facet indices.

        """
        vertices = np.unique(self.facets[:, ix].flatten())

        if self.dim() == 3:
            edge_candidates = self.t2e[:, self.f2t[0, ix]].flatten()
            # subset of edges that share all points with the given facets
            subset = np.nonzero(
                np.prod(np.isin(self.edges[:, edge_candidates],
                                self.facets[:, ix].flatten()),
                        axis=0)
            )[0]
            edges = np.intersect1d(self.boundary_edges(),
                                   edge_candidates[subset])
        else:
            edges = np.array([], dtype=np.int64)

        return vertices, edges

    def _mapping(self):
        """Return a default reference mapping for the mesh."""
        from skfem.mapping import MappingAffine, MappingIsoparametric
        if not hasattr(self, '_cached_mapping'):
            fakemesh = namedtuple('FakeMesh', ['p', 't', 'facets', 't2f', 'f2t', 'dim'])(
                self.doflocs,
                self.dofs.element_dofs,
                self.facets,
                self.t2f,
                self.f2t,
                lambda: self.dim(),
            )
            if self.affine:
                self._cached_mapping = MappingAffine(fakemesh)
            else:
                self._cached_mapping = MappingIsoparametric(
                    fakemesh,
                    self.elem(),
                    self.bndelem,
                )
        return self._cached_mapping

    def _init_facets(self):
        """Initialize ``self.facets``."""
        self._facets, self._t2f = self.build_entities(
            self.t,
            self.elem.refdom.facets
        )

    def _init_edges(self):
        """Initialize ``self.edges``."""
        self._edges, self._t2e = self.build_entities(
            self.t,
            self.elem.refdom.edges
        )

    def __post_init__(self):
        """Support node orders used in external formats.

        We expect ``self.doflocs`` to be ordered based on the
        degrees-of-freedom in :class:`skfem.assembly.Dofs`.  External formats
        for high order meshes commonly use a less strict ordering scheme and
        the extra nodes are described as additional rows in ``self.t``.  This
        method attempts to accommodate external formas by reordering
        ``self.doflocs`` and changing the indices in ``self.t``.

        """
        if not isinstance(self.doflocs, ndarray):
            # for backwards-compatibility: support standard lists
            self.doflocs = np.array(self.doflocs, dtype=np.float64)

        if not isinstance(self.t, ndarray):
            # for backwards-compatibility: support standard lists
            self.t = np.array(self.t, dtype=np.int64)

        M = self.elem.refdom.nnodes

        if self.nnodes > M:  # TODO check that works for 3D quadratic
            # reorder DOFs to the expected format: vertex DOFs are first
            p, t = self.doflocs, self.t
            _t = t[:M]
            uniq, ix = np.unique(_t, return_inverse=True)
            self.t = np.arange(len(uniq), dtype=np.int64)[ix].reshape(_t.shape)
            _p = np.hstack((
                p[:, uniq],
                np.zeros((p.shape[0], np.max(t) + 1 - len(uniq))),
            ))
            _p[:, self.dofs.element_dofs[M:].flatten('F')] =\
                p[:, t[M:].flatten('F')]
            self.doflocs = _p


    def save(self,
             filename: str,
             point_data: Optional[Dict[str, ndarray]] = None,
             **kwargs) -> None:
        """Export the mesh and fields using meshio.

        Parameters
        ----------
        filename
            The output filename, with suffix determining format;
            e.g. .msh, .vtk, .xdmf
        point_data
            Data related to the vertices of the mesh.

        """
        from skfem.io.meshio import to_file
        return to_file(self, filename, point_data, **kwargs)

    @classmethod
    def load(cls, filename):
        from skfem.io.meshio import from_file
        return from_file(filename)

    @classmethod
    def from_mesh(cls, mesh):
        """Reuse an existing mesh by adding nodes.

        Parameters
        ----------
        mesh
            The mesh used in the initialization.  Connectivity of the new mesh
            will match ``mesh.t``.

        """
        from skfem.assembly import Dofs

        mapping = mesh._mapping()
        nelem = cls.elem
        dofs = Dofs(mesh, nelem())
        locs = mapping.F(nelem.doflocs.T)
        doflocs = np.zeros((locs.shape[0], dofs.N))

        # match mapped dofs and global dof numbering
        for itr in range(locs.shape[0]):
            for jtr in range(dofs.element_dofs.shape[0]):
                doflocs[itr, dofs.element_dofs[jtr]] = locs[itr, :, jtr]

        return cls(
            doflocs=doflocs,
            t=mesh.t,
        )

    @classmethod
    def init_refdom(cls):
        """Initialize a mesh corresponding to the reference domain."""
        return cls(cls.elem.refdom.p, cls.elem.refdom.t)

    def refined(self, times_or_ix: Union[int, ndarray] = 1):
        """Return a refined mesh.

        Parameters
        ----------
        times_or_ix
            Either an integer giving the number of uniform refinements or an
            array of element indices for adaptive refinement.

        """
        m = self
        if isinstance(times_or_ix, int):
            for _ in range(times_or_ix):
                m = m._uniform()
        else:    
            m = m._adaptive(times_or_ix)
        return m

    def scaled(self, factors):
        """Return a new mesh with scaled dimensions.

        Parameters
        ----------
        factors
            Scale each dimension by a factor.

        """
        return replace(
            self,
            doflocs=np.array([self.doflocs[itr] * factors[itr]
                              for itr in range(len(factors))]),
        )

    def translated(self, diffs):
        """Return a new translated mesh.

        Parameters
        ----------
        diffs
            Translate the mesh by a vector. Must have same size as the mesh
            dimension.

        """
        return replace(
            self,
            doflocs=np.array([self.doflocs[itr] + diffs[itr]
                              for itr in range(len(diffs))]),
        )

    def _uniform(self):
        """Perform a single uniform refinement."""
        raise NotImplementedError

    def _adaptive(self, ix: ndarray):
        """Adaptively refine the given set of elements."""
        raise NotImplementedError

    def _splitref(self, nrefs: int = 1):
        """Split mesh into separate nonconnected elements and refine.

        Used for visualization purposes.

        Parameters
        ----------
        nrefs
            The number of refinements.

        """
        cls = type(self)
        m = cls.init_refdom().refined(nrefs)
        X = m.p
        x = self._mapping().F(m.p)

        # create connectivity for the new mesh
        nt = self.nelements
        t = np.tile(m.t, (1, nt))
        dt = np.max(t)
        t += ((dt + 1)
              * (np.tile(np.arange(nt), (m.t.shape[0] * m.t.shape[1], 1))
                 .flatten('F')
                 .reshape((-1, m.t.shape[0])).T))

        if X.shape[0] == 1:
            p = np.array([x.flatten()])
        else:
            p = x[0].flatten()
            for itr in range(len(x) - 1):
                p = np.vstack((p, x[itr + 1].flatten()))

        return cls(p, t)

    @staticmethod
    def build_entities(t, indices):
        """Build low dimensional topological entities."""
        indexing = np.hstack(tuple([t[ix] for ix in indices]))
        sorted_indexing = np.sort(indexing, axis=0)

        sorted_indexing, ixa, ixb = np.unique(sorted_indexing,
                                              axis=1,
                                              return_index=True,
                                              return_inverse=True)
        mapping = ixb.reshape((len(indices), t.shape[1]))

        return np.ascontiguousarray(indexing[:, ixa]), mapping

    @staticmethod
    def build_inverse(t, mapping):
        """Build inverse mapping from low dimensional topological entities."""
        e = mapping.flatten(order='C')
        tix = np.tile(np.arange(t.shape[1]), (1, t.shape[0]))[0]

        e_first, ix_first = np.unique(e, return_index=True)
        e_last, ix_last = np.unique(e[::-1], return_index=True)
        ix_last = e.shape[0] - ix_last - 1

        inverse = np.zeros((2, np.max(mapping) + 1), dtype=np.int64)
        inverse[0, e_first] = tix[ix_first]
        inverse[1, e_last] = tix[ix_last]
        inverse[1, np.nonzero(inverse[0] == inverse[1])[0]] = -1

        return inverse

    @staticmethod
    def strip_extra_coordinates(p: ndarray) -> ndarray:
        """Fallback for 3D meshes."""
        return p

    def param(self) -> float:
        """Return mesh parameter, viz the length of the longest edge."""
        raise NotImplementedError


@dataclass
class BaseMesh2D(BaseMesh):

    def param(self) -> float:
        return np.max(
            np.linalg.norm(np.diff(self.p[:, self.facets], axis=1), axis=0)
        )

    @staticmethod
    def strip_extra_coordinates(p: ndarray) -> ndarray:
        """For meshio which appends :math:`z = 0` to 2D meshes."""
        return p[:, :2]

    def _repr_svg_(self) -> str:
        from skfem.visuals.svg import draw
        return draw(self, nrefs=2, boundaries_only=True)


@dataclass
class BaseMesh3D(BaseMesh):

    def param(self) -> float:
        return np.max(
            np.linalg.norm(np.diff(self.p[:, self.edges], axis=1), axis=0)
        )


@dataclass
class MeshTri1(BaseMesh2D):

    doflocs: ndarray = np.array([[0., 1., 0., 1.],
                                 [0., 0., 1., 1.]], dtype=np.float64)
    t: ndarray = np.array([[0, 1],
                           [1, 3],
                           [2, 2]], dtype=np.int64)
    elem: Type[Element] = ElementTriP1
    affine: bool = True

    def _uniform(self):

        p = self.doflocs
        t = self.t
        t2f = self.t2f
        sz = p.shape[1]
        return replace(
            self,
            doflocs=np.hstack((p, p[:, self.facets].mean(axis=1))),
            t=np.hstack((
                np.vstack((t[0], t2f[0] + sz, t2f[2] + sz)),
                np.vstack((t[1], t2f[0] + sz, t2f[1] + sz)),
                np.vstack((t[2], t2f[2] + sz, t2f[1] + sz)),
                np.vstack((t2f[0] + sz, t2f[1] + sz, t2f[2] + sz)),
            )),
        )

    def _adaptive(self, marked):
        """Refine the set of marked elements."""

        def sort_mesh(p, t):
            """Make (0, 2) the longest edge in t."""
            l01 = np.sqrt(np.sum((p[:, t[0]] - p[:, t[1]]) ** 2, axis=0))
            l12 = np.sqrt(np.sum((p[:, t[1]] - p[:, t[2]]) ** 2, axis=0))
            l02 = np.sqrt(np.sum((p[:, t[0]] - p[:, t[2]]) ** 2, axis=0))

            ix01 = (l01 > l02) * (l01 > l12)
            ix12 = (l12 > l01) * (l12 > l02)

            # row swaps
            tmp = t[2, ix01]
            t[2, ix01] = t[1, ix01]
            t[1, ix01] = tmp

            tmp = t[0, ix12]
            t[0, ix12] = t[1, ix12]
            t[1, ix12] = tmp

            return t

        def find_facets(m, marked_elems):
            """Find the facets to split."""
            facets = np.zeros(m.facets.shape[1], dtype=np.int64)
            facets[m.t2f[:, marked_elems].flatten('F')] = 1
            prev_nnz = -1e10

            while np.count_nonzero(facets) - prev_nnz > 0:
                prev_nnz = np.count_nonzero(facets)
                t2facets = facets[m.t2f]
                t2facets[2, t2facets[0, :] + t2facets[1, :] > 0] = 1
                facets[m.t2f[t2facets == 1]] = 1

            return facets

        def split_elements(m, facets):
            """Define new elements."""
            ix = (-1)*np.ones(m.facets.shape[1], dtype=np.int64)
            ix[facets == 1] = (np.arange(np.count_nonzero(facets))
                               + m.p.shape[1])
            ix = ix[m.t2f]

            red =   (ix[0] >= 0) * (ix[1] >= 0) * (ix[2] >= 0)  # noqa
            blue1 = (ix[0] ==-1) * (ix[1] >= 0) * (ix[2] >= 0)  # noqa
            blue2 = (ix[0] >= 0) * (ix[1] ==-1) * (ix[2] >= 0)  # noqa
            green = (ix[0] ==-1) * (ix[1] ==-1) * (ix[2] >= 0)  # noqa
            rest =  (ix[0] ==-1) * (ix[1] ==-1) * (ix[2] ==-1)  # noqa

            # new red elements
            t_red = np.hstack((
                np.vstack((m.t[0, red], ix[0, red], ix[2, red])),
                np.vstack((m.t[1, red], ix[0, red], ix[1, red])),
                np.vstack((m.t[2, red], ix[1, red], ix[2, red])),
                np.vstack(( ix[1, red], ix[2, red], ix[0, red])),  # noqa
            ))

            # new blue elements
            t_blue1 = np.hstack((
                np.vstack((m.t[1, blue1], m.t[0, blue1], ix[2, blue1])),
                np.vstack((m.t[1, blue1],  ix[1, blue1], ix[2, blue1])),  # noqa
                np.vstack((m.t[2, blue1],  ix[2, blue1], ix[1, blue1])),  # noqa
            ))

            t_blue2 = np.hstack((
                np.vstack((m.t[0, blue2], ix[0, blue2],  ix[2, blue2])),  # noqa
                np.vstack(( ix[2, blue2], ix[0, blue2], m.t[1, blue2])),  # noqa
                np.vstack((m.t[2, blue2], ix[2, blue2], m.t[1, blue2])),
            ))

            # new green elements
            t_green = np.hstack((
                np.vstack((m.t[1, green], ix[2, green], m.t[0, green])),
                np.vstack((m.t[2, green], ix[2, green], m.t[1, green])),
            ))

            # new nodes
            p = .5 * (m.p[:, m.facets[0, facets == 1]] +
                      m.p[:, m.facets[1, facets == 1]])

            return (
                np.hstack((m.p, p)),
                np.hstack((m.t[:, rest], t_red, t_blue1, t_blue2, t_green)),
            )

        sorted_mesh = replace(
            self,
            t=sort_mesh(self.p, self.t)
        )
        facets = find_facets(sorted_mesh, marked)
        doflocs, t = split_elements(sorted_mesh, facets)

        return replace(
            self,
            doflocs=doflocs,
            t=t,
        )


@dataclass
class MeshQuad1(BaseMesh2D):

    doflocs: ndarray = np.array([[0., 1., 1., 0.],
                                 [0., 0., 1., 1.]], dtype=np.float64)
    t: ndarray = np.array([[0],
                           [1],
                           [2],
                           [3]], dtype=np.int64)
    elem: Type[Element] = ElementQuad1

    def _uniform(self):

        p = self.doflocs
        t = self.t
        t2f = self.t2f
        sz = p.shape[1]
        mid = np.arange(t.shape[1], dtype=np.int64) + np.max(t2f) + sz + 1
        return replace(
            self,
            doflocs=np.hstack((
                p,
                p[:, self.facets].mean(axis=1),
                p[:, self.t].mean(axis=1),
            )),
            t=np.hstack((
                np.vstack((t[0], t2f[0] + sz, mid, t2f[3] + sz)),
                np.vstack((t2f[0] + sz, t[1], t2f[1] + sz, mid)),
                np.vstack((mid, t2f[1] + sz, t[2], t2f[2] + sz)),
                np.vstack((t2f[3] + sz, mid, t2f[2] + sz, t[3])),
            )),
        )

    def to_meshtri(self, x: Optional[ndarray] = None):

        t = self.t[[0, 1, 3]]
        t = np.hstack((t, self.t[[1, 2, 3]]))
        mesh = MeshTri1(self.doflocs, t)

        if x is not None:
            if len(x) == self.t.shape[1]:
                # preserve elemental constant functions
                X = np.concatenate((x, x))
            else:
                raise Exception("The parameter x must have one value per "
                                "element.")
            return mesh, X
        return mesh


@dataclass
class MeshTri2(MeshTri1):

    elem: Type[Element] = ElementTriP2
    affine: bool = False


@dataclass
class MeshQuad2(MeshQuad1):

    elem: Type[Element] = ElementQuad2


@dataclass
class MeshTet1(BaseMesh3D):

    doflocs: ndarray = np.array([[0., 0., 0.],
                                 [0., 0., 1.],
                                 [0., 1., 0.],
                                 [1., 0., 0.],
                                 [0., 1., 1.],
                                 [1., 0., 1.],
                                 [1., 1., 0.],
                                 [1., 1., 1.]], dtype=np.float64).T
    t: ndarray = np.array([[0, 1, 2, 3],
                           [3, 5, 1, 7],
                           [2, 3, 6, 7],
                           [2, 3, 1, 7],
                           [1, 2, 4, 7]], dtype=np.int64).T
    elem: Type[Element] = ElementTetP1
    affine: bool = True

    def _uniform(self):

        t = self.t
        p = self.p
        e = self.edges
        sz = p.shape[1]
        t2e = self.t2e + sz

        # new vertices are the midpoints of edges
        newp = .5 * np.vstack((p[0, e[0]] + p[0, e[1]],
                               p[1, e[0]] + p[1, e[1]],
                               p[2, e[0]] + p[2, e[1]]))
        newp = np.hstack((p, newp))
        # new tets
        newt = np.vstack((t[0], t2e[0], t2e[2], t2e[3]))
        newt = np.hstack((newt, np.vstack((t[1], t2e[0], t2e[1], t2e[4]))))
        newt = np.hstack((newt, np.vstack((t[2], t2e[1], t2e[2], t2e[5]))))
        newt = np.hstack((newt, np.vstack((t[3], t2e[3], t2e[4], t2e[5]))))

        # compute middle pyramid diagonal lengths and choose shortest
        d1 = ((newp[0, t2e[2]] - newp[0, t2e[4]]) ** 2 +
              (newp[1, t2e[2]] - newp[1, t2e[4]]) ** 2)
        d2 = ((newp[0, t2e[1]] - newp[0, t2e[3]]) ** 2 +
              (newp[1, t2e[1]] - newp[1, t2e[3]]) ** 2)
        d3 = ((newp[0, t2e[0]] - newp[0, t2e[5]]) ** 2 +
              (newp[1, t2e[0]] - newp[1, t2e[5]]) ** 2)
        I1 = d1 < d2
        I2 = d1 < d3
        I3 = d2 < d3
        c1 = I1 * I2
        c2 = (~I1) * I3
        c3 = (~I2) * (~I3)
        # splitting the pyramid in the middle;
        # diagonals are [2,4], [1,3] and [0,5]

        # case 1: diagonal [2,4]
        newt = np.hstack((newt, np.vstack((t2e[2, c1], t2e[4, c1],
                                           t2e[0, c1], t2e[1, c1]))))
        newt = np.hstack((newt, np.vstack((t2e[2, c1], t2e[4, c1],
                                           t2e[0, c1], t2e[3, c1]))))
        newt = np.hstack((newt, np.vstack((t2e[2, c1], t2e[4, c1],
                                           t2e[1, c1], t2e[5, c1]))))
        newt = np.hstack((newt, np.vstack((t2e[2, c1], t2e[4, c1],
                                           t2e[3, c1], t2e[5, c1]))))
        # case 2: diagonal [1,3]
        newt = np.hstack((newt, np.vstack((t2e[1, c2], t2e[3, c2],
                                           t2e[0, c2], t2e[4, c2]))))
        newt = np.hstack((newt, np.vstack((t2e[1, c2], t2e[3, c2],
                                           t2e[4, c2], t2e[5, c2]))))
        newt = np.hstack((newt, np.vstack((t2e[1, c2], t2e[3, c2],
                                           t2e[5, c2], t2e[2, c2]))))
        newt = np.hstack((newt, np.vstack((t2e[1, c2], t2e[3, c2],
                                           t2e[2, c2], t2e[0, c2]))))
        # case 3: diagonal [0,5]
        newt = np.hstack((newt, np.vstack((t2e[0, c3], t2e[5, c3],
                                           t2e[1, c3], t2e[4, c3]))))
        newt = np.hstack((newt, np.vstack((t2e[0, c3], t2e[5, c3],
                                           t2e[4, c3], t2e[3, c3]))))
        newt = np.hstack((newt, np.vstack((t2e[0, c3], t2e[5, c3],
                                           t2e[3, c3], t2e[2, c3]))))
        newt = np.hstack((newt, np.vstack((t2e[0, c3], t2e[5, c3],
                                           t2e[2, c3], t2e[1, c3]))))
        # update fields

        return replace(
            self,
            doflocs=newp,
            t=newt,
        )


@dataclass
class MeshHex1(BaseMesh3D):

    doflocs: ndarray = np.array([[0., 0., 0.],
                                 [0., 0., 1.],
                                 [0., 1., 0.],
                                 [1., 0., 0.],
                                 [0., 1., 1.],
                                 [1., 0., 1.],
                                 [1., 1., 0.],
                                 [1., 1., 1.]], dtype=np.float64).T
    t: ndarray = np.array([[0, 1, 2, 3, 4, 5, 6, 7]], dtype=np.int64).T
    elem: Type[Element] = ElementHex1

    def _uniform(self):

        p = self.doflocs
        t = self.t
        sz = p.shape[1]
        t2e = self.t2e.copy() + sz
        t2f = self.t2f.copy() + np.max(t2e) + 1
        mid = range(self.t.shape[1]) + np.max(t2f) + 1

        doflocs = np.hstack((
            p,
            .5 * np.sum(p[:, self.edges], axis=1),
            .25 * np.sum(p[:, self.facets], axis=1),
            .125 * np.sum(p[:, t], axis=1),
        ))
        t = np.hstack((
            np.vstack((
                t[0], t2e[0], t2e[1], t2e[2], t2f[0], t2f[2], t2f[1], mid
            )),
            np.vstack((
                t2e[0], t[1], t2f[0], t2f[2], t2e[3],t2e[4], mid, t2f[4]
            )),
            np.vstack((
                t2e[1], t2f[0], t[2], t2f[1], t2e[5], mid, t2e[6], t2f[3]
            )),
            np.vstack((
                t2e[2], t2f[2], t2f[1], t[3], mid, t2e[7], t2e[8], t2f[5]
            )),
            np.vstack((
                t2f[0], t2e[3], t2e[5], mid, t[4], t2f[4], t2f[3], t2e[9]
            )),
            np.vstack((
                t2f[2], t2e[4], mid, t2e[7], t2f[4], t[5], t2f[5], t2e[10]
            )),
            np.vstack((
                t2f[1], mid, t2e[6], t2e[8], t2f[3], t2f[5], t[6], t2e[11]
            )),
            np.vstack((
                mid, t2f[4], t2f[3], t2f[5], t2e[9], t2e[10], t2e[11], t[7]
            ))
        ))

        return replace(self, doflocs=doflocs, t=t)
