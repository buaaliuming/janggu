"""Dna dataset"""

import os

import numpy as np
from HTSeq import GenomicInterval

from janggo.data.data import Dataset
from janggo.data.genomic_indexer import GenomicIndexer
from janggo.data.genomicarray import create_genomic_array
from janggo.utils import _complement_index
from janggo.utils import as_onehot
from janggo.utils import dna2ind
from janggo.utils import sequences_from_fasta


class Dna(Dataset):
    """Dna class.

    This datastructure holds a DNA sequence for the purpose of a deep learning
    application.
    The sequence can conventiently fetched from a raw fasta-file.
    Upon indexing or slicing of the dataset, the one-hot representation
    for the respective locus will be returned.

    Note
    ----
    Caching is only used with storage mode 'memmap' or 'hdf5'.
    We recommend to use 'hdf5' for performance reasons.

    Parameters
    -----------
    name : str
        Name of the dataset
    garray : :class:`GenomicArray`
        A genomic array that holds the sequence data.
    gindxer : :class:`GenomicIndexer`
        A genomic index mapper that translates an integer index to a
        genomic coordinate.
    flank : int
        Flanking regions in basepairs to be extended up and downstream.
        Default: 150.
    order : int
        Order for the one-hot representation. Default: 1.
    cachedir : str or None
        Directory in which the cachefiles are located. Default: None.

    """

    _order = None
    _flank = None

    def __init__(self, name, garray, gindexer, flank=150, order=1):

        self.flank = flank
        self.order = order
        self.garray = garray
        self.gindexer = gindexer
        self._rcindex = [_complement_index(idx, order)
                         for idx in range(pow(4, order))]

        Dataset.__init__(self, '{}'.format(name))

    @staticmethod
    def _make_genomic_array(name, fastafile, order, storage, cachedir='',
                            overwrite=False):
        """Create a genomic array or reload an existing one."""

        # always use int 16 to store dna indices
        # do not use int8 at the moment, because 'N' is encoded
        # as -1024, which causes an underflow with int8.
        dtype = 'int16'

        # Load sequences from refgenome
        seqs = []
        if isinstance(fastafile, str):
            fastafile = [fastafile]

        for fasta in fastafile:
            # += is necessary since sequences_from_fasta
            # returns a list
            seqs += sequences_from_fasta(fasta)

        # Extract chromosome lengths
        chromlens = {}

        for seq in seqs:
            chromlens[seq.id] = len(seq) - order + 1

        def _dna_loader(cover, seqs, order):
            print('Convert sequences to index array')
            for seq in seqs:
                interval = GenomicInterval(seq.id, 0,
                                           len(seq) - order + 1, '.')

                dna = np.asarray(dna2ind(seq), dtype=dtype)

                if order > 1:
                    # for higher order motifs, this part is used
                    filter_ = np.asarray([pow(4, i) for i in range(order)])
                    dna = np.convolve(dna, filter_, mode='valid')

                cover[interval, 0] = dna

        # At the moment, we treat the information contained
        # in each bw-file as unstranded

        cover = create_genomic_array(chromlens, stranded=False,
                                     storage=storage,
                                     memmap_dir=os.path.join(cachedir, name),
                                     overwrite=overwrite,
                                     typecode=dtype,
                                     loader=_dna_loader,
                                     loader_args=(seqs, order))

        return cover

    @classmethod
    def create_from_refgenome(cls, name, refgenome, regions,
                              stepsize=200, reglen=200,
                              flank=0, order=1, storage='ndarray',
                              cachedir='', overwrite=False):
        """Create a Dna class from a reference genome.

        This requires a reference genome in fasta format as well as a bed-file
        that holds the regions of interest.

        Parameters
        -----------
        name : str
            Name of the dataset
        refgenome : str
            Fasta file.
        regions : str
            BED- or GFF-filename.
        reglen : int
            Region length in basepairs to be considered. Default: 200.
        stepsize : int
            stepsize in basepairs for traversing the genome. Default: 200.
        flank : int
            Flanking regions in basepairs to be extended up and downstream.
            Default: 0.
        order : int
            Order for the one-hot representation. Default: 1.
        storage : str
            Storage mode for storing the sequence may be 'ndarray', 'memmap' or
            'hdf5'. Default: 'hdf5'.
        cachedir : str
            Directory in which the cachefiles are located. Default: ''.
        """
        # fill up int8 rep of DNA
        # load dna, region index, and within region index

        gindexer = GenomicIndexer.create_from_file(regions, reglen, stepsize)

        garray = cls._make_genomic_array(name, refgenome, order, storage,
                                         cachedir=cachedir,
                                         overwrite=overwrite)

        return cls(name, garray, gindexer, flank, order)

    @classmethod
    def create_from_fasta(cls, name, fastafile, storage='ndarray',
                          order=1, cachedir='', overwrite=False):
        """Create a Dna class from a fastafile.

        This allows to load sequence of equal lengths to be loaded from
        a fastafile.

        Parameters
        -----------
        name : str
            Name of the dataset
        fastafile : str or list(str)
            Fasta file or list of fasta files.
        order : int
            Order for the one-hot representation. Default: 1.
        storage : str
            Storage mode for storing the sequence may be 'ndarray', 'memmap' or
            'hdf5'. Default: 'ndarray'.
        cachedir : str
            Directory in which the cachefiles are located. Default: ''.
        overwrite : boolean
            Overwrite the cachefiles. Default: False.
        """
        garray = cls._make_genomic_array(name, fastafile, order, storage,
                                         cachedir=cachedir,
                                         overwrite=overwrite)

        seqs = []
        if isinstance(fastafile, str):
            fastafile = [fastafile]

        for fasta in fastafile:
            seqs += sequences_from_fasta(fasta)

        # Check if sequences are equally long
        lens = [len(seq) for seq in seqs]
        assert lens == [len(seqs[0])] * len(seqs), "Input sequences must " + \
            "be of equal length."

        # Chromnames are required to be Unique
        chroms = [seq.id for seq in seqs]
        assert len(set(chroms)) == len(seqs), "Sequence IDs must be unique."
        # now mimic a dataframe representing a bed file

        reglen = lens[0]
        flank = 0
        stepsize = 1

        gindexer = GenomicIndexer(reglen, stepsize, 1)
        gindexer.chrs = chroms
        gindexer.offsets = [0]*len(lens)
        gindexer.inregionidx = [0]*len(lens)
        gindexer.strand = ['.']*len(lens)
        gindexer.rel_end = [reglen + 2*flank]*len(lens)

        return cls(name, garray, gindexer, flank, order)

    def __repr__(self):  # pragma: no cover
        return 'Dna("{}", <garray>, <gindexer>, \
                flank={}, order={})'\
                .format(self.name, self.flank, self.order)

    def idna4idx(self, idxs):
        """Extracts the DNA sequence for set of indices.

        This method gets as input a list of indices (e.g.
        corresponding to genomic ranges for a given batch) and returns
        the respective sequences as an index array.

        Parameters
        ----------
        idxs : list(int)
            List of region indexes

        Returns
        -------
        numpy.array
            Nucleotide sequences associated with the regions
            with shape `(len(idxs), sequence_length + 2*flank - order + 1)`
        """

        # for each index read use the adaptor indices to retrieve the seq.
        idna = np.zeros((len(idxs), self.gindexer.binsize +
                         2*self.flank - self.order + 1), dtype="int16")

        for i, idx in enumerate(idxs):
            interval = self.gindexer[idx]
            interval.start -= self.flank
            interval.end += self.flank - self.order + 1

            # Computing the forward or reverse complement of the
            # sequence, depending on the strand flag.
            if interval.strand in ['.', '+']:
                idna[i] = np.asarray(self.garray[interval][:, 0, 0])
            else:
                idna[i] = np.asarray(
                    [self._rcindex[val] for val in self.garray[interval][:, 0, 0]])[::-1]

        return idna

    def __getitem__(self, idxs):
        if isinstance(idxs, int):
            idxs = [idxs]
        if isinstance(idxs, slice):
            idxs = range(idxs.start if idxs.start else 0,
                         idxs.stop if idxs.stop else len(self),
                         idxs.step if idxs.step else 1)
        try:
            iter(idxs)
        except TypeError:
            raise IndexError('Dna.__getitem__: '
                             + 'index must be iterable')

        data = as_onehot(self.idna4idx(idxs), self.order)

        for transform in self.transformations:
            data = transform(data)

        return data

    def __len__(self):
        return len(self.gindexer)

    @property
    def shape(self):
        """Shape of the dataset"""
        return (len(self), self.gindexer.binsize +
                2*self.flank - self.order + 1, pow(4, self.order), 1)

    @property
    def order(self):
        """Order of the one-hot representation"""
        return self._order

    @order.setter
    def order(self, value):
        if not isinstance(value, int) or value < 1:
            raise Exception('order must be a positive integer')
        if value > 4:
            raise Exception('order support only up to order=4.')
        self._order = value

    @property
    def flank(self):
        """Flanking bins"""
        return self._flank

    @flank.setter
    def flank(self, value):
        if not isinstance(value, int) or value < 0:
            raise Exception('_flank must be a non-negative integer')
        self._flank = value
