#!/usr/bin/env python

import argparse
import os
from ccmpred import CCMpred
import ccmpred.logo
import ccmpred.io.alignment
import ccmpred.raw
import ccmpred.weighting
import ccmpred.sampling
import ccmpred.gaps
import ccmpred.trees
import ccmpred.parameter_handling
import numpy as np

EPILOG = """
Generate a multiple sequence alignment of protein sequences generated from a Markov Random Field model.

In a first step, coupling potentials will have to be learned from a source protein MSA using 
e.g. CCMpred with the --write-msgpack command. 
This can then be passed to the CCMgen call.

"""


def parse_args():
    parser = argparse.ArgumentParser(epilog=EPILOG)

    parser.add_argument("rawfile", help="Raw coupling potential file as generated by the CCMpred --write-msgpack option")
    parser.add_argument("alnfile", help="Input alignment file to use.")
    parser.add_argument("outalnfile", help="Output alignment file for sampled sequences.")

    grp_tr = parser.add_argument_group("Phylogenetic Tree Options")
    grp_tr_me = grp_tr.add_mutually_exclusive_group()
    grp_tr_me.add_argument("--tree-newick",    dest="tree_file", type=str, default=None,
                        help="Load tree from newick-formatted file")
    grp_tr_me.add_argument("--tree-binary",    dest="tree_source", action="store_const", const="binary",
                        help="Generate binary tree")
    grp_tr_me.add_argument("--tree-star",      dest="tree_source", action="store_const", const="star",
                        help="Generate star tree")

    grp_tr_opt = parser.add_argument_group("Phylogenetic Tree Sampling Options")
    grp_tr_opt_me = grp_tr_opt.add_mutually_exclusive_group()
    grp_tr_opt_me.add_argument("--mutation-rate", dest="mutation_rate", type=float, default=0.0,
                        help="Specify constant mutation rate")
    grp_tr_opt_me.add_argument("--mutation-rate-neff", dest="mutation_rate_neff", action="store_true", default=False,
                        help="Set mutation rate to generate alignment with Neff comparable to original MSA")
    grp_tr_opt.add_argument("--burn-in", dest="burn_in", type=int, default=500,
                        help="Specify number of Gibbs steps for defining ancestor sequence [default: %(default)s]")
    grp_tr_opt.add_argument("--num-sequences", dest="nseq", type=int, default=0,
                        help="Set the number of sequences to generate to NSEQ [default: N]")

    grp_mcmc = parser.add_argument_group("MCMC Sampling Options")
    grp_mcmc.add_argument("--mcmc-sampling",      dest="mcmc", action="store_true", default=False,
                        help="Generate MCMC sample without following tree topology.")
    grp_mcmc.add_argument("--mcmc-sample-original", dest="mcmc_sample_type", action="store_const", const="original",
                          default="original", help="Sample sequences starting from original sequences.")
    grp_mcmc.add_argument("--mcmc-sample-random",   dest="mcmc_sample_type", action="store_const", const="random",
                          help="Sample sequences starting from random sequences")
    grp_mcmc.add_argument("--mcmc-sample-random-gapped", dest="mcmc_sample_type", action="store_const", const="random-gapped",
                          help="Sample sequences starting from random sequences but keeping original gap structures "
                               "[default: %(default)s]")
    grp_mcmc.add_argument("--mcmc-burn-in", dest="mcmc_burn_in", type=int, default=500,
                          help="Number of Gibbs sampling steps before a sample is obtained.")
    grp_mcmc.add_argument("--mcmc-nseq", dest="mcmc_nseq", type=int, default=10000,
                          help="Set the number of sequences to generate to MCMC_NSEQ [default: %(default)s]")

    grp_constraints = parser.add_argument_group("Use with Contraints (couplings for non-contacts will be set to zero)")
    grp_constraints.add_argument("--pdb-file", dest="pdbfile", help="Input PDB file")
    grp_constraints.add_argument("--contact-threshold", dest="contact_threshold", type=int, default=8,
                           help="Definition of residue pairs forming a contact wrt distance of their Cbeta atoms in "
                                "angstrom. [default: %(default)s]")

    grp_opt = parser.add_argument_group("General Options")
    grp_opt.add_argument("--max-gap-pos",  dest="max_gap_pos", default=100, type=int,
                        help="Ignore alignment positions with > MAX_GAP_POS percent gaps. [default: %(default)s == no removal of gaps]")
    grp_opt.add_argument("--max-gap-seq",  dest="max_gap_seq",  default=100, type=int,
                        help="Remove sequences with >X percent gaps. [default: %(default)s == no removal of sequences]")
    grp_opt.add_argument("--aln-format", dest="aln_format", type=str, default="fasta",
                        help="Specify format for alignment files [default: %(default)s]")
    grp_opt.add_argument("-t", "--num_threads", dest="num_threads", type=int, default=1,
                        help="Specify the number of threads. [default: %(default)s]")



    opt = parser.parse_args()

    if not opt.mcmc and not opt.tree_source and not opt.tree_file:
        parser.error("Need one of the --tree-* options or --mcmc-sampling!")


    if opt.tree_source or opt.tree_file:
        if not opt.mutation_rate and not opt.mutation_rate_neff:
            parser.error("Need one of the --mutation-rate* options!")

    return opt


def main():

    # read command line options
    opt = parse_args()

    ccmpred.logo.logo(what_for="ccmgen")

    # set OMP environment variable for number of threads
    os.environ['OMP_NUM_THREADS'] = str(opt.num_threads)
    print("Using {0} threads for OMP parallelization.".format(os.environ["OMP_NUM_THREADS"]))

    # instantiate CCMpred
    ccm = CCMpred()

    # specify possible file paths
    ccm.set_alignment_file(opt.alnfile)
    ccm.set_initraw_file(opt.rawfile)
    ccm.set_pdb_file(opt.pdbfile)

    # read alignment and possible remove gapped sequences and positions
    ccm.read_alignment(opt.aln_format, opt.max_gap_pos, opt.max_gap_seq)

    #read potentials from binary raw file
    ccm.intialise_potentials()

    # read pdb file if CCMpred is a constrained run
    if opt.pdbfile:
        ccm.read_pdb(opt.contact_threshold)
        print("Couplings for pairs with Cbeta distances > {0} will be set to zero!".format(opt.contact_threshold))
        ccm.x_pair[ccm.non_contact_indices[0], ccm.non_contact_indices[1], :, :] = 0


        ##############################################################
    # ccm.x_pair = np.zeros((ccm.L, ccm.L, 21, 21))
    # print("summe x_pair: {0}".format(np.sum(ccm.x_pair)))
    #
    # ccm.compute_frequencies("uniform_pseudocounts", pseudocount_n_single=1, pseudocount_n_pair=1)
    #
    # single_freq = ccm.pseudocounts.freqs[0]
    # id_inf = np.sum(single_freq[:,:20]*single_freq[:,:20]) / ccm.L
    # print("id_inf (freq norm with gaps) = {0}".format(id_inf))
    #
    # single_freq = ccm.pseudocounts.degap(single_freq)
    # id_inf = np.sum(single_freq[:,:20]*single_freq[:,:20]) / ccm.L
    # print("id_inf (freq degapped)= {0}".format(id_inf))
    #
    # p = np.exp(ccm.x_single) / np.sum(np.exp(ccm.x_single), axis=1)[:, np.newaxis]
    # id_inf = np.sum(p[:,:20]*p[:,:20]) / ccm.L
    # print("id_inf (model prob)= {0}".format(id_inf))
        ##############################################################
    x = ccmpred.parameter_handling.structured_to_linear(ccm.x_single, ccm.x_pair, nogapstate=True, padding=False)

    #determine number of sequences of sample
    if opt.nseq == 0:
        opt.nseq = ccm.N

    #prepare tree topology
    tree = ccmpred.trees.CCMTree()
    tree.specify_tree(opt.nseq, tree_file=opt.tree_file, tree_source=opt.tree_source)

    #start sampling along tree
    if tree is not None and opt.mutation_rate_neff:
        msa_sampled, neff = ccmpred.sampling.sample_to_neff_increasingly(
            tree, ccm.neff_entropy, ccm.L, x, opt.burn_in)
    # elif tree is not None and opt.sample_aln_stat_correlation:
    #     # compute amino acid counts and frequencies adding pseudo counts for non-observed amino acids
    #     ccm.compute_frequencies("uniform_pseudocounts", 1, 1)
    #
    #     single_freq_observed, pairwise_freq_observed = ccm.pseudocounts.freqs
    #     single_freq_observed = ccm.pseudocounts.degap(single_freq_observed, False)
    #     pairwise_freq_observed = ccm.pseudocounts.degap(pairwise_freq_observed, False)
    #
    #     msa_sampled, neff = ccmpred.sampling.sample_to_pair_correlation(
    #         tree, ccm.neff_entropy, ccm.L, x, opt.burn_in, single_freq_observed, pairwise_freq_observed)
    elif tree is not None and opt.mutation_rate > 0:
        msa_sampled, neff = ccmpred.sampling.sample_with_mutation_rate(
            tree, ccm.L, x, opt.burn_in, opt.mutation_rate)
    else:
        msa_sampled, neff = ccmpred.sampling.generate_mcmc_sample(
            x, ccm.msa, size=opt.mcmc_nseq, burn_in=opt.mcmc_burn_in, sample_type=opt.mcmc_sample_type)


    # if gappy positions have been removed
    # insert columns with gaps at that position
    if ccm.max_gap_pos < 100:
        msa_sampled = ccmpred.gaps.backinsert_gapped_positions_aln(
            msa_sampled, ccm.gapped_positions
        )


    print("\nWriting sampled alignment to {0}".format(opt.outalnfile))
    with open(opt.outalnfile, "w") as f:
        descs=["synthetic sequence generated with CCMgen" for _ in range(msa_sampled.shape[0])]
        if tree is not None:
            ids = tree.ids
        else:
            ids = ["seq {0}".format(i) for i in range(msa_sampled.shape[0])]
        ccmpred.io.alignment.write_msa(f, msa_sampled, tree.ids, is_indices=True, format=opt.aln_format, descriptions=descs)


if __name__ == '__main__':
    main()
