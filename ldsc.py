'''
(c) 2014 Brendan Bulik-Sullivan and Hilary Finucane

This is a command line application for estimating
	1. LD Score and friends (L1, L1^2, L2 and L4)
	2. heritability / partitioned heritability
	3. genetic covariance
	4. genetic correlation
	5. block jackknife standard errors for all of the above.
	
	
'''
from __future__ import division
import ldscore.ldscore as ld
import ldscore.parse as ps
import ldscore.jackknife as jk
import argparse
import numpy as np
import pandas as pd
from subprocess import call
from itertools import product

__version__ = '0.0.1 (alpha)'

MASTHEAD = "*********************************************************************\n"
MASTHEAD += "* LD Score Regression (LDSC)\n"
MASTHEAD += "* version {V}\n".format(V=__version__)
MASTHEAD += "* (C) 2014 Brendan Bulik-Sullivan and Hilary Finucane\n"
MASTHEAD += "* Broad Institute of MIT and Harvard / MIT Department of Mathematics\n"
MASTHEAD += "* GNU General Public License v3\n"
MASTHEAD += "*********************************************************************\n"

pd.set_option('display.max_rows', 500)
pd.set_option('display.max_columns', 500)
pd.set_option('display.width', 1000)
pd.set_option('precision', 4)
np.set_printoptions(linewidth=1000)
np.set_printoptions(precision=4)


class logger(object):
	'''
	Lightweight logging.
	
	TODO: replace with logging module
	
	'''
	def __init__(self, fh):
		self.log_fh = open(fh, 'wb')
		
 	def log(self, msg):
		'''
		Print to log file and stdout with a single command.
		
		'''
		print >>self.log_fh, msg
		print msg
	

def __filter__(fname, noun, verb, merge_obj):
	merged_list = None
	if fname:
		f = lambda x,n: x.format(noun=noun, verb=verb, fname=fname, num=n)
		x = ps.FilterFile(fname)
	 	c = 'Read list of {num} {noun} to {verb} from {fname}'
	 	print f(c, len(x.IDList))
		merged_list = merge_obj.loj(x.IDList)
		len_merged_list = len(merged_list)
		if len_merged_list > 0:
			c = 'After merging, {num} {noun} remain'
			print f(c, len_merged_list)
		else:
			error_msg = 'No {noun} retained for analysis'
			raise ValueError(f(error_msg, 0))

		return merged_list
		

def _print_cov(hsqhat, ofh, log):
	'''Prints covariance matrix of slopes'''
	log.log('Printing covariance matrix of the estimates to {F}'.format(F=ofh))
	np.savetxt(ofh, hsqhat.hsq_cov)


def _print_gencov_cov(hsqhat, ofh, log):
	'''Prints covariance matrix of slopes'''
	log.log('Printing covariance matrix of the estimates to {F}'.format(F=ofh))
	np.savetxt(ofh, hsqhat.gencov_cov)


def _print_delete_k(hsqhat, ofh, log):
	'''Prints block jackknife delete-k values'''
	log.log('Printing block jackknife delete-k values to {F}'.format(F=ofh))
	out_mat = hsqhat._jknife.delete_values
	if hsqhat.constrain_intercept is None:
		ncol = out_mat.shape[1]
		out_mat = out_mat[:,0:ncol-1]
		
	np.savetxt(ofh, out_mat)

	
def annot_sort_key(s):
	'''For use with --cts-bin. Fixes weird pandas crosstab column order.'''
	if type(s) == tuple:
		s = [x.split('_')[0] for x in s]
		s = map(lambda x: float(x) if x != 'min' else -float('inf'), s)
	else: #type(s) = str:	
		s = s.split('_')[0]
		if s == 'min': 
			s = float('-inf')
		else:
			s = float(s)
				
 	return s


def ldscore(args, header=None):
	'''
	Wrapper function for estimating l1, l1^2, l2 and l4 (+ optionally standard errors) from
	reference panel genotypes. 
	
	Annot format is 
	chr snp bp cm <annotations>
	
	'''
	log = logger(args.out+'.log')
	if header:
		log.log(header)
	#log.log(args)
	
	if args.bin:
		snp_file, snp_obj = args.bin+'.bim', ps.PlinkBIMFile
		ind_file, ind_obj = args.bin+'.ind', ps.VcfINDFile
		array_file, array_obj = args.bin+'.bin', ld.VcfBINFile
	elif args.bfile:
		snp_file, snp_obj = args.bfile+'.bim', ps.PlinkBIMFile
		ind_file, ind_obj = args.bfile+'.fam', ps.PlinkFAMFile
		array_file, array_obj = args.bfile+'.bed', ld.PlinkBEDFile

	# read bim/snp
	array_snps = snp_obj(snp_file)
	m = len(array_snps.IDList)
	log.log('Read list of {m} SNPs from {f}'.format(m=m, f=snp_file))

	# read --annot
	if args.annot is not None:
		annot = ps.AnnotFile(args.annot)
		num_annots, ma = len(annot.df.columns) - 4, len(annot.df)
		log.log("Read {A} annotations for {M} SNPs from {f}".format(f=args.annot,
			A=num_annots, M=ma))
		annot_matrix = np.array(annot.df.iloc[:,4:])
		annot_colnames = annot.df.columns[4:]
		keep_snps = None
		if np.any(annot.df.SNP.values != array_snps.df.SNP.values):
			raise ValueError('The .annot file must contain the same SNPs in the same'+\
				' order as the .bim or .snp file')
	# read --extract
	elif args.extract is not None:
		keep_snps = __filter__(args.extract, 'SNPs', 'include', array_snps)
		annot_matrix, annot_colnames, num_annots = None, None, 1
	
	# read cts_bin_add
	elif args.cts_bin_add is not None and args.cts_breaks is not None:
		# read filenames
		cts_fnames = args.cts_bin_add.split(',')
		# read breaks
		# replace N with negative sign
		args.cts_breaks = args.cts_breaks.replace('N','-')
		# split on x
		try:
			breaks = [[float(x) for x in y.split(',')] for y in args.cts_breaks.split('x')]
		except ValueError as e:
			raise ValueError('--cts-breaks must be a comma-separated list of numbers: '
				+str(e.args))
	
		if len(breaks) != len(cts_fnames):
			raise ValueError('Need to specify one set of breaks for each file in --cts-bin.')
		
		if args.cts_names:
			cts_colnames = [str(x) for x in args.cts_names.split(',')]
			if len(cts_colnames) != len(cts_fnames):
				msg = 'Must specify either no --cts-names or one value for each file in --cts-bin.'
				raise ValueError(msg)

		else:
			cts_colnames = ['ANNOT'+str(i) for i in xrange(len(cts_fnames))]
			
		log.log('Reading numbers with which to bin SNPs from {F}'.format(F=args.cts_bin_add))
	
		cts_levs = []
		full_labs = []
		first_lev = np.zeros((m,))
		for i,fh in enumerate(cts_fnames):
			vec = ps.read_cts(cts_fnames[i], array_snps.df.SNP.values)
			
			max_cts = np.max(vec)
			min_cts = np.min(vec)
			cut_breaks = list(breaks[i])
			name_breaks = list(cut_breaks)
			if np.all(cut_breaks >= max_cts) or np.all(cut_breaks <= min_cts):
				raise ValueError('All breaks lie outside the range of the cts variable.')

			if np.all(cut_breaks <= max_cts):
				name_breaks.append(max_cts)
				cut_breaks.append(max_cts+1)
		
			if np.all(cut_breaks >= min_cts):	
				name_breaks.append(min_cts)
				cut_breaks.append(min_cts-1)

			name_breaks.sort()
			cut_breaks.sort()		
			n_breaks = len(cut_breaks)
			# so that col names are consistent across chromosomes with different max vals
			name_breaks[0] = 'min'
			name_breaks[-1] = 'max'
			name_breaks = [str(x) for x in name_breaks]
			labs = [name_breaks[i]+'_'+name_breaks[i+1] for i in xrange(n_breaks-1)]
			cut_vec = pd.Series(pd.cut(vec, bins=cut_breaks, labels=labs))
			full_labs.append(labs)
			small_annot_matrix = cut_vec
			# crosstab -- for now we keep empty columns
			small_annot_matrix = pd.crosstab(small_annot_matrix.index, 
				small_annot_matrix, dropna=False)
			small_annot_matrix = small_annot_matrix[sorted(small_annot_matrix.columns, key=annot_sort_key)]
			cts_levs.append(small_annot_matrix.ix[:,1:])
			# first column defaults to no annotation
			first_lev += small_annot_matrix.ix[:,0]
	
		if len(cts_colnames) == 1:
			annot_colnames = [cts_colnames[0]+'_'+bin for bin in full_labs[0]]
		else:
			annot_colnames = []
			for i,cname in enumerate(cts_colnames):
				for bin in full_labs[i][1:]:
					annot_colnames.append(cts_colnames[i]+'_'+bin)
					
		annot_colnames.insert(0, "BOTTOM_BINS")
		first_lev = np.minimum(first_lev, 1)
		cts_levs.insert(0, pd.DataFrame(first_lev))
		annot_matrix = pd.concat(cts_levs, axis=1)
		annot_matrix = np.matrix(annot_matrix)
		keep_snps = None
		num_annots = annot_matrix.shape[1]

	# read --cts-bin plus --cts-breaks
	elif args.cts_bin is not None and args.cts_breaks is not None:
		# read filenames
		cts_fnames = args.cts_bin.split(',')
		# read breaks
		# replace N with negative sign
		args.cts_breaks = args.cts_breaks.replace('N','-')
		# split on x
		try:
			breaks = [[float(x) for x in y.split(',')] for y in args.cts_breaks.split('x')]
		except ValueError as e:
			raise ValueError('--cts-breaks must be a comma-separated list of numbers: '
				+str(e.args))
	
		if len(breaks) != len(cts_fnames):
			raise ValueError('Need to specify one set of breaks for each file in --cts-bin.')
		
		if args.cts_names:
			cts_colnames = [str(x) for x in args.cts_names.split(',')]
			if len(cts_colnames) != len(cts_fnames):
				msg = 'Must specify either no --cts-names or one value for each file in --cts-bin.'
				raise ValueError(msg)

		else:
			cts_colnames = ['ANNOT'+str(i) for i in xrange(len(cts_fnames))]
			
		log.log('Reading numbers with which to bin SNPs from {F}'.format(F=args.cts_bin))
	
		cts_levs = []
		full_labs = []
		for i,fh in enumerate(cts_fnames):
			vec = ps.read_cts(cts_fnames[i], array_snps.df.SNP.values)
			
			max_cts = np.max(vec)
			min_cts = np.min(vec)
			cut_breaks = list(breaks[i])
			name_breaks = list(cut_breaks)
			if np.all(cut_breaks >= max_cts) or np.all(cut_breaks <= min_cts):
				raise ValueError('All breaks lie outside the range of the cts variable.')

			if np.all(cut_breaks <= max_cts):
				name_breaks.append(max_cts)
				cut_breaks.append(max_cts+1)
		
			if np.all(cut_breaks >= min_cts):	
				name_breaks.append(min_cts)
				cut_breaks.append(min_cts-1)

			name_breaks.sort()
			cut_breaks.sort()		
			n_breaks = len(cut_breaks)
			# so that col names are consistent across chromosomes with different max vals
			name_breaks[0] = 'min'
			name_breaks[-1] = 'max'
			name_breaks = [str(x) for x in name_breaks]
			labs = [name_breaks[i]+'_'+name_breaks[i+1] for i in xrange(n_breaks-1)]
			cut_vec = pd.Series(pd.cut(vec, bins=cut_breaks, labels=labs))
			cts_levs.append(cut_vec)
			full_labs.append(labs)

		annot_matrix = pd.concat(cts_levs, axis=1)
		annot_matrix.columns = cts_colnames
		# crosstab -- for now we keep empty columns
		annot_matrix = pd.crosstab(annot_matrix.index, 
			[annot_matrix[i] for i in annot_matrix.columns], dropna=False,
			colnames=annot_matrix.columns)

		# add missing columns
		if len(cts_colnames) > 1:
			for x in product(*full_labs)		:
				if x not in annot_matrix.columns:
					annot_matrix[x] = 0
		else:
			for x in full_labs[0]:
				if x not in annot_matrix.columns:
					annot_matrix[x] = 0
				
		annot_matrix = annot_matrix[sorted(annot_matrix.columns, key=annot_sort_key)]
		if len(cts_colnames) > 1:
			# flatten multi-index
			annot_colnames = ['_'.join([cts_colnames[i]+'_'+b for i,b in enumerate(c)])
				for c in annot_matrix.columns]
		else:
			annot_colnames = [cts_colnames[0]+'_'+b for b in annot_matrix.columns]

		annot_matrix = np.matrix(annot_matrix)
		keep_snps = None
		num_annots = len(annot_colnames)
		if np.any(np.sum(annot_matrix, axis=1) == 0):
 			# This exception should never be raised. For debugging only.
 			raise ValueError('Some SNPs have no annotation in --cts-bin. This is a bug!')

	else:
		annot_matrix, annot_colnames, keep_snps = None, None, None, 
		num_annots = 1
	
	# read fam/ind
	array_indivs = ind_obj(ind_file)
	n = len(array_indivs.IDList)	 
	log.log('Read list of {n} individuals from {f}'.format(n=n, f=ind_file))
	# read keep_indivs
	if args.keep:
		keep_indivs = __filter__(args.keep, 'individuals', 'include', array_indivs)
	else:
		keep_indivs = None
	
	# read genotype array
	log.log('Reading genotypes from {fname}'.format(fname=array_file))
	geno_array = array_obj(array_file, n, array_snps, keep_snps=keep_snps,
		keep_indivs=keep_indivs, mafMin=args.maf)
		
	# filter annot_matrix down to only SNPs passing MAF cutoffs
	if annot_matrix is not None:
		annot_keep = geno_array.kept_snps
		annot_matrix = annot_matrix[annot_keep,:]
	
	# determine block widths
	x = np.array((args.ld_wind_snps, args.ld_wind_kb, args.ld_wind_cm), dtype=bool)
	if np.sum(x) != 1: 
		raise ValueError('Must specify exactly one --ld-wind option')
	
	if args.ld_wind_snps:
		max_dist = args.ld_wind_snps
		coords = np.array(xrange(geno_array.m))
	elif args.ld_wind_kb:
		max_dist = args.ld_wind_kb*1000
		coords = np.array(array_snps.df['BP'])[geno_array.kept_snps]
	elif args.ld_wind_cm:
		max_dist = args.ld_wind_cm
		coords = np.array(array_snps.df['CM'])[geno_array.kept_snps]

	block_left = ld.getBlockLefts(coords, max_dist)
	if block_left[len(block_left)-1] == 0 and not args.yes_really:
		error_msg = 'Do you really want to compute whole-chomosome LD Score? If so, set the '
		error_msg += '--yes-really flag (warning: it will use a lot of time / memory)'
		raise ValueError(error_msg)

	scale_suffix = ''
	if args.pq_exp is not None:
		log.log('Computing LD with pq ^ {S}.'.format(S=args.pq_exp))
		msg = 'Note that LD Scores with pq raised to a nonzero power are'
		msg += 'not directly comparable to normal LD Scores.'
		log.log(msg)
		scale_suffix = '_S{S}'.format(S=args.pq_exp)
		pq = np.matrix(geno_array.maf*(1-geno_array.maf)).reshape((geno_array.m,1))
		pq = np.power(pq, args.pq_exp)

		if annot_matrix is not None:
			annot_matrix = np.multiply(annot_matrix, pq)
		else:
			annot_matrix = pq
	
	elif args.maf_exp is not None:
		log.log('Computing LD with MAF ^ {S}.'.format(S=args.maf_exp))
		msg = 'Note that LD Scores with MAF raised to a nonzero power are'
		msg += 'not directly comparable to normal LD Scores.'
		log.log(msg)
		scale_suffix = '_S{S}'.format(S=args.maf_exp)
		mf = np.matrix(geno_array.maf).reshape((geno_array.m,1))
		mf = np.power(mf, args.maf_exp)

		if annot_matrix is not None:
			annot_matrix = np.multiply(annot_matrix, mf)
		else:
			annot_matrix = mf
	
# 	if args.se: # block jackknife
# 
# 		# block size
# 		if args.block_size:
# 			jSize = args.block_size 
# 		elif n > 50:
# 			jSize = 10
# 		else:
# 			jSize = 1
# 		
# 		jN = int(np.ceil(n / jSize))
# 		if args.l1:
# 			col_prefix = "L1"; file_suffix = "l1.jknife"
# 			raise NotImplementedError('Sorry, havent implemented L1 block jackknife yet.')
# 			
# 		elif args.l1sq:
# 			col_prefix = "L1SQ"; file_suffix = "l1sq.jknife"
# 			raise NotImplementedError('Sorry, havent implemented L1^2 block jackknife yet.')
# 			
# 		elif args.l2:
# 			col_prefix = "L2"; file_suffix = "l2.jknife"
# 			c = "Computing LD Score (L2) and block jackknife standard errors with {n} blocks."
# 			
# 		elif args.l4:
# 			col_prefix = "L4"; file_suffix = "l4.jknife"
# 			c = "Computing L4 and block jackknife standard errors with {n} blocks."
# 			
# 		print c.format(n=jN)
# 		(lN_est, lN_se) = geno_array.ldScoreBlockJackknife(block_left, args.chunk_size, jN=jN,
# 			annot=annot_matrix)
# 		lN = np.c_[lN_est, lN_se]
# 		if num_annots == 1:
# 			ldscore_colnames = [col_prefix+scale_suffix, 'SE('+col_prefix+scale_suffix+')']
# 		else:
# 			ldscore_colnames =  [x+col_prefix+scale_suffix for x in annot_colnames]
# 			ldscore_colnames += ['SE('+x+scale_suffix+')' for x in ldscore_colnames]

# 	else: # not block jackknife
# 		if args.l1:
# 			log.log("Estimating L1.")
# 			lN = geno_array.l1VarBlocks(block_left, args.chunk_size, annot=annot_matrix)
# 			col_prefix = "L1"; file_suffix = "l1"
# 		
# 		elif args.l1sq:
# 			log.log("Estimating L1 ^ 2.")
# 			lN = geno_array.l1sqVarBlocks(block_left, args.chunk_size, annot=annot_matrix)
# 			col_prefix = "L1SQ"; file_suffix = "l1sq"
# 		
# 		elif args.l2:
# 			log.log("Estimating LD Score (L2).")
# 			lN = geno_array.ldScoreVarBlocks(block_left, args.chunk_size, annot=annot_matrix)
# 			col_prefix = "L2"; file_suffix = "l2"
# 				
# 		elif args.l4:
# 			col_prefix = "L4"; file_suffix = "l4"
# 			raise NotImplementedError('Sorry, havent implemented L4 yet. Try the jackknife.')
# 			lN = geno_array.l4VarBlocks(block_left, c, annot)
		
	log.log("Estimating LD Score.")
	lN = geno_array.ldScoreVarBlocks(block_left, args.chunk_size, annot=annot_matrix)
	col_prefix = "L2"; file_suffix = "l2"

	if num_annots == 1:
		ldscore_colnames = [col_prefix+scale_suffix]
	else:
		ldscore_colnames =  [x+col_prefix+scale_suffix for x in annot_colnames]
			
	# print .ldscore
	# output columns: CHR, BP, CM, RS, MAF, [LD Scores and optionally SEs]
	out_fname = args.out + '.' + file_suffix + '.ldscore'
	new_colnames = geno_array.colnames + ldscore_colnames
	df = pd.DataFrame.from_records(np.c_[geno_array.df, lN])
	df.columns = new_colnames
	if args.print_snps:
		if args.print_snps.endswith('gz'):
			print_snps = pd.read_csv(args.print_snps, header=None, compression='gzip')
		elif args.print_snps.endswith('bz2'):
			print_snps = pd.read_csv(args.print_snps, header=None, compression='bz2')
		else:
			print_snps = pd.read_csv(args.print_snps, header=None)
		if len(print_snps.columns) > 1:
			raise ValueError('--print-snps must refer to a file with a one column of SNP IDs.')
		log.log('Reading list of {N} SNPs for which to print LD Scores from {F}'.format(\
						F=args.print_snps, N=len(print_snps)))

		print_snps.columns=['SNP']
		df = df.ix[df.SNP.isin(print_snps.SNP),:]
		if len(df) == 0:
			raise ValueError('After merging with --print-snps, no SNPs remain.')
		else:
			msg = 'After merging with --print-snps, LD Scores for {N} SNPs will be printed.'
			log.log(msg.format(N=len(df)))
	
	log.log("Writing LD Scores for {N} SNPs to {f}.gz".format(f=out_fname, N=len(df)))
	df.to_csv(out_fname, sep="\t", header=True, index=False)	
	call(['gzip', '-f', out_fname])
		
	# print .M
	if annot_matrix is not None:
		M = np.atleast_1d(np.squeeze(np.asarray(np.sum(annot_matrix, axis=0))))
		ii = geno_array.maf > 0.05
		M_5_50 = np.atleast_1d(np.squeeze(np.asarray(np.sum(annot_matrix[ii,:], axis=0))))
	else:
		M = [geno_array.m]
		M_5_50 = [np.sum(geno_array.maf > 0.05)]
	
	# print .M
	fout_M = open(args.out + '.'+ file_suffix +'.M','wb')
	print >>fout_M, '\t'.join(map(str,M))
	fout_M.close()
	
	# print .M_5_50
	fout_M_5_50 = open(args.out + '.'+ file_suffix +'.M_5_50','wb')
	print >>fout_M_5_50, '\t'.join(map(str,M_5_50))
	fout_M_5_50.close()
	
	# print annot matrix
	if (args.cts_bin is not None or args.cts_bin_add is not None) and not args.no_print_annot:
		out_fname = args.out + '.annot'
		new_colnames = geno_array.colnames + ldscore_colnames
		annot_df = pd.DataFrame(np.c_[geno_array.df, annot_matrix])
		annot_df.columns = new_colnames	
		del annot_df['MAF']
		log.log("Writing annot matrix produced by --cts-bin to {F}".format(F=out_fname+'.gz'))
		annot_df.to_csv(out_fname, sep="\t", header=True, index=False)	
		call(['gzip', '-f', out_fname])
	
	# print LD Score summary	
	pd.set_option('display.max_rows', 200)
	log.log('')
	log.log('Summary of {F}:'.format(F=out_fname))
	t = df.ix[:,4:].describe()
	log.log( t.ix[1:,:] )
	
	# print correlation matrix including all LD Scores and sample MAF
	log.log('')
	log.log('MAF/LD Correlation Matrix')
	log.log( df.ix[:,4:].corr() )
	
	# print condition number
	if num_annots > 1: # condition number of a column vector w/ nonzero var is trivially one
		log.log('')
		log.log('LD Score Matrix Condition Number')
		cond_num = np.linalg.cond(df.ix[:,5:])
		log.log( jk.kill_brackets(str(np.matrix(cond_num))) )
		if cond_num > 10000:
			log.log('WARNING: ill-conditioned LD Score Matrix!')
		

def sumstats(args, header=None):
	'''
	Wrapper function for estmating
		1. h2 / partitioned h2
		2. genetic covariance / correlation
		3. LD Score regression intercept
	
	from reference panel LD and GWAS summary statistics.
	
	'''
	
	# open output files
	log = logger(args.out + ".log")
	if header:
		log.log(header)
	
	# read .chisq or betaprod
	try:
		if args.h2:
			chisq = args.h2+'.chisq.gz'
			log.log('Reading summary statistics from {S}.'.format(S=chisq))
			sumstats = ps.chisq(chisq)
		elif args.intercept:
			chisq = args.intercept+'.chisq.gz'
			log.log('Reading summary statistics from {S}.'.format(S=chisq))
			sumstats = ps.chisq(chisq)
		elif args.rg:
			try:
				(p1, p2) = args.rg.split(',')
			except ValueError as e:
				log.log('Error: argument to --rg must be two .chisq/.allele fileset prefixes separated by a comma.')
				raise e
				
			chisq1 = p1 + '.chisq.gz'
			chisq2 = p2 + '.chisq.gz'
			allele1 = p1 + '.allele.gz'
			allele2 = p2 + '.allele.gz'
			sumstats = ps.betaprod_fromchisq(chisq1, chisq2, allele1, allele2)
	except ValueError as e:
		log.log('Error parsing summary statistics.')
		raise e
	
	log_msg = 'Read summary statistics for {N} SNPs.'
	log.log(log_msg.format(N=len(sumstats)))
	
	# read reference panel LD Scores
	try:
		if args.ref_ld:
			ref_ldscores = ps.ldscore(args.ref_ld)
		elif args.ref_ld_chr:
			ref_ldscores = ps.ldscore(args.ref_ld_chr,22)
		elif args.ref_ld_fromfile:
			ref_ldscores = ps.ldscore_fromfile(args.ref_ld_fromfile)
		elif args.ref_ld_fromfile_chr:
			ref_ldscores = ps.ldscore_fromfile(args.ref_ld_fromfile,22)

	except ValueError as e:
		log.log('Error parsing reference LD.')
		raise e
				
	# read --M
	if args.M:
		try:
			M_annot = [float(x) for x in args.M.split(',')]
		except TypeError as e:
			raise TypeError('Count not case --M to float: ' + str(e.args))
		
		if len(M_annot) != len(ref_ldscores.columns) - 1:
			msg = 'Number of comma-separated terms in --M must match the number of partitioned'
			msg += 'LD Scores in --ref-ld'
			raise ValueError(msg)
		
	# read .M or --M-file			
	else:
		if args.M_file:
			if args.ref_ld:
				M_annot = ps.M(args.M_file)	
			elif args.ref_ld_chr:
				M_annot = ps.M(args.M_file, 22)
		elif args.not_M_5_50:
			if args.ref_ld:
				M_annot = ps.M(args.ref_ld)	
			elif args.ref_ld_chr:
				M_annot = ps.M(args.ref_ld_chr, 22)
		else:
			if args.ref_ld:
				M_annot = ps.M(args.ref_ld, common=True)	
			elif args.ref_ld_chr:
				M_annot = ps.M(args.ref_ld_chr, 22, common=True)
			elif args.ref_ld_fromfile:
				M_annot = ps.M_fromfile(args.ref_ld_fromfile)
			elif args.ref_ld_fromfile_chr:
				M_annot = ps.M_fromfile(args.ref_ld_fromfile_chr, 22)
				
		# filter ref LD down to those columns specified by --keep-ld
		if args.keep_ld is not None:
			try:
				keep_M_indices = [int(x) for x in args.keep_ld.split(',')]
				keep_ld_colnums = [int(x)+1 for x in args.keep_ld.split(',')]
			except ValueError as e:
				raise ValueError('--keep-ld must be a comma-separate list of column numbers: '\
					+str(e.args))
	
			if len(keep_ld_colnums) == 0:
				raise ValueError('No reference LD columns retained by --keep-ld')
	
			keep_ld_colnums = [0] + keep_ld_colnums
			try:
				M_annot = [M_annot[i] for i in keep_M_indices]
				ref_ldscores = ref_ldscores.ix[:,keep_ld_colnums]
			except IndexError as e:
				raise IndexError('--keep-ld column numbers are out of bounds: '+str(e.args))
		
	log.log('Using M = '+str(np.array(M_annot)).replace('[','').replace(']','') ) # convert to np to use np printoptions
	
	ii = np.squeeze(np.array(ref_ldscores.iloc[:,1:len(ref_ldscores.columns)].var(axis=0) == 0))
	if np.any(ii):
		log.log('Removing partitioned LD Scores with zero variance')
		ii = np.insert(ii, 0, False) # keep the SNP column		
		ref_ldscores = ref_ldscores.ix[:,np.logical_not(ii)]
		M_annot = [M_annot[i] for i in xrange(1,len(ii)) if not ii[i]]
		n_annot = len(M_annot)
			
	log_msg = 'Read reference panel LD Scores for {N} SNPs.'
	log.log(log_msg.format(N=len(ref_ldscores)))

	# read regression SNP LD Scores
	try:
		if args.w_ld:
			w_ldscores = ps.ldscore(args.w_ld)
		elif args.w_ld_chr:
			w_ldscores = ps.ldscore(args.w_ld_chr, 22)

	except ValueError as e:
		log.log('Error parsing regression SNP LD')
		raise e
	
	# to keep the column names from being the same
	w_ldscores.columns = ['SNP','LD_weights'] 

	log_msg = 'Read LD Scores for {N} SNPs to be retained for regression.'
	log.log(log_msg.format(N=len(w_ldscores)))
	
	# merge with reference panel LD Scores 
	sumstats = pd.merge(sumstats, ref_ldscores, how="inner", on="SNP")
	if len(sumstats) == 0:
		raise ValueError('No SNPs remain after merging with reference panel LD')
	else:
		log_msg = 'After merging with reference panel LD, {N} SNPs remain.'
		log.log(log_msg.format(N=len(sumstats)))

	# merge with regression SNP LD Scores
	sumstats = pd.merge(sumstats, w_ldscores, how="inner", on="SNP")
	if len(sumstats) <= 1:
		raise ValueError('No SNPs remain after merging with regression SNP LD')
	else:
		log_msg = 'After merging with regression SNP LD, {N} SNPs remain.'
		log.log(log_msg.format(N=len(sumstats)))
	
	ref_ld_colnames = ref_ldscores.columns[1:len(ref_ldscores.columns)]	
	w_ld_colname = sumstats.columns[-1]
	del(ref_ldscores); del(w_ldscores)
	
	err_msg = 'No SNPs retained for analysis after filtering on {C} {P} {F}.'
	log_msg = 'After filtering on {C} {P} {F}, {N} SNPs remain.'
	loop = ['1','2'] if args.rg else ['']
	var_to_arg = {'infomax': args.info_max, 'infomin': args.info_min, 'maf': args.maf}
	var_to_cname  = {'infomax': 'INFO', 'infomin': 'INFO', 'maf': 'MAF'}
	var_to_pred = {'infomax': lambda x: x < args.info_max, 
		'infomin': lambda x: x > args.info_min, 
		'maf': lambda x: x > args.maf}
	var_to_predstr = {'infomax': '<', 'infomin': '>', 'maf': '>'}
	for v in var_to_arg.keys():
		arg = var_to_arg[v]; pred = var_to_pred[v]; pred_str = var_to_predstr[v]
		for p in loop:
			cname = var_to_cname[v] + p; 
			if arg is not None:
				sumstats = ps.filter_df(sumstats, cname, pred)
				snp_count = len(sumstats)
				if snp_count == 0:
					raise ValueError(err_msg.format(C=cname, F=arg, P=pred_str))
				else:
					log.log(log_msg.format(C=cname, F=arg, N=snp_count, P=pred_str))

	# check condition number of LD Score Matrix
	if len(M_annot) > 1:
		cond_num = np.linalg.cond(sumstats[ref_ld_colnames])
		if cond_num > 100000:
			if args.invert_anyway:
				warn = "WARNING: LD Score matrix condition number is {C}. "
				warn += "Inverting anyway because the --invert-anyway flag is set."
				log.log(warn)
			else:
				warn = "WARNING: LD Score matrix condition number is {C}. "
				warn += "Remove collinear LD Scores or force inversion with "
				warn += "the --invert-anyway flag."
				log.log(warn.format(C=cond_num))
				raise ValueError(warn.format(C=cond_num))

	if len(sumstats) < args.num_blocks:
		args.num_blocks = len(sumstats)

	log.log('Estimating standard errors using a block jackknife with {N} blocks.'.format(N=args.num_blocks))
	if len(sumstats) < 200000:
		log.log('WARNING: number of SNPs less than 200k; this is almost always bad.')

	# LD Score regression intercept
	if args.intercept:
		log.log('Estimating LD Score regression intercept.')
		# filter out large-effect loci
		max_N = np.max(sumstats['N'])
		if not args.no_filter_chisq:
			max_chisq = max(0.001*max_N, 20)
			sumstats = sumstats[sumstats['CHISQ'] < max_chisq]
			log_msg = 'After filtering on chi^2 < {C}, {N} SNPs remain.'
			log.log(log_msg.format(C=max_chisq, N=len(sumstats)))
	
			snp_count = len(sumstats)
			if snp_count == 0:
				raise ValueError(log_msg.format(C=max_chisq, N='no'))
			else:
				log.log(log_msg.format(C=max_chisq, N=len(sumstats)))

		snp_count = len(sumstats); n_annot = len(ref_ld_colnames)
		ref_ld = np.matrix(sumstats[ref_ld_colnames]).reshape((snp_count, n_annot))
		w_ld = np.matrix(sumstats[w_ld_colname]).reshape((snp_count, 1))
		M_annot = np.matrix(M_annot).reshape((1, n_annot))
		chisq = np.matrix(sumstats.CHISQ).reshape((snp_count, 1))
		N = np.matrix(sumstats.N).reshape((snp_count,1))
		del sumstats
		hsqhat = jk.Hsq(chisq, ref_ld, w_ld, N, M_annot, args.num_blocks)				
		log.log(hsqhat.summary_intercept())
		return hsqhat
		
		
	# LD Score regression to estimate h2
	elif args.h2:
	
		log.log('Estimating heritability.')
		max_N = np.max(sumstats['N'])
		if not args.no_filter_chisq:
			max_chisq = max(0.001*max_N, 80)
			sumstats = sumstats[sumstats['CHISQ'] < max_chisq]
			log_msg = 'After filtering on chi^2 < {C}, {N} SNPs remain.'
			log.log(log_msg.format(C=max_chisq, N=len(sumstats)))
			
		snp_count = len(sumstats); n_annot = len(ref_ld_colnames)
		ref_ld = np.matrix(sumstats[ref_ld_colnames]).reshape((snp_count, n_annot))
		w_ld = np.matrix(sumstats[w_ld_colname]).reshape((snp_count, 1))
		M_annot = np.matrix(M_annot).reshape((1,n_annot))
		chisq = np.matrix(sumstats.CHISQ).reshape((snp_count, 1))
		N = np.matrix(sumstats.N).reshape((snp_count,1))
		del sumstats

		if args.no_intercept:
			args.constrain_intercept = 1

		if args.constrain_intercept:
			try:
				intercept = float(args.constrain_intercept)
			except Exception as e:
				err_type = type(e).__name__
				e = ' '.join([str(x) for x in e.args])
				e = err_type+': '+e
				msg = 'Could not coerce argument to --constrain-intercept to floats.\n '+e
				raise ValueError(msg)
				
			log.log('Constraining LD Score regression intercept = {C}.'.format(C=intercept))
			hsqhat = jk.Hsq(chisq, ref_ld, w_ld, N, M_annot, args.num_blocks,
				args.non_negative, intercept)
					
		elif args.aggregate:
			if args.annot:
				annot = ps.AnnotFile(args.annot)
				num_annots,ma = len(annot.df.columns) - 4, len(annot.df)
				log.log("Read {A} annotations for {M} SNPs from {f}.".format(f=args.annot,
					A=num_annots,	M=ma))
				annot_matrix = np.matrix(annot.df.iloc[:,4:])
			else:
				raise ValueError("No annot file specified.")

			hsqhat = jk.Hsq_aggregate(chisq, ref_ld, w_ld, N, M_annot, annot_matrix, args.num_blocks)
			log.log(hsqhat.summary(ref_ld_colnames))
		else:
			hsqhat = jk.Hsq(chisq, ref_ld, w_ld, N, M_annot, args.num_blocks,
				args.non_negative)
		
		if not args.human_only and n_annot > 1:
			hsq_cov_ofh = args.out+'.hsq.cov'
			_print_cov(hsqhat, hsq_cov_ofh, log)
					
		if args.print_delete_vals:
			hsq_delete_ofh = args.out+'.delete_k'
			_print_delete_k(hsqhat, hsq_delete_ofh, log)
	
		log.log(hsqhat.summary(ref_ld_colnames))
			
		return [M_annot,hsqhat]


	# LD Score regression to estimate genetic correlation
	elif args.rg or args.rg or args.rg:
		log.log('Estimating genetic correlation.')

		max_N1 = np.max(sumstats['N1'])
		max_N2 = np.max(sumstats['N2'])
		if not args.no_filter_chisq:
			max_chisq1 = max(0.001*max_N1, 80)
			max_chisq2 = max(0.001*max_N2, 80)
			chisq1 = sumstats.BETAHAT1**2 * sumstats.N1
			chisq2 = sumstats.BETAHAT2**2 * sumstats.N2
			ii = np.logical_and(chisq1 < max_chisq1, chisq2 < max_chisq2)
			sumstats = sumstats[ii]
			log_msg = 'After filtering on chi^2 < ({C},{D}), {N} SNPs remain.'
			log.log(log_msg.format(C=max_chisq1, D=max_chisq2, N=np.sum(ii)))

		snp_count = len(sumstats); n_annot = len(ref_ld_colnames)
		ref_ld = np.matrix(sumstats[ref_ld_colnames]).reshape((snp_count, n_annot))
		w_ld = np.matrix(sumstats[w_ld_colname]).reshape((snp_count, 1))
		M_annot = np.matrix(M_annot).reshape((1, n_annot))
		betahat1 = np.matrix(sumstats.BETAHAT1).reshape((snp_count, 1))
		betahat2 = np.matrix(sumstats.BETAHAT2).reshape((snp_count, 1))
		N1 = np.matrix(sumstats.N1).reshape((snp_count,1))
		N2 = np.matrix(sumstats.N2).reshape((snp_count,1))
		del sumstats
		
		if args.no_intercept:
			args.constrain_intercept = "1,1,0"
		
		if args.constrain_intercept:
			intercepts = args.constrain_intercept.split(',')
			if len(intercepts) != 3:
				msg = 'If using --constrain-intercept with --sumstats-gencor, must specify a ' 
				msg += 'comma-separated list of three intercepts. '
				msg += 'The first two for the h2 estimates; the third for the gencov estimate.'
				raise ValueError(msg)
	
			try:
				intercepts = [float(x) for x in intercepts]
			except Exception as e:
				err_type = type(e).__name__
				e = ' '.join([str(x) for x in e.args])
				e = err_type+': '+e
				msg = 'Could not coerce arguments to --constrain-intercept to floats.\n '+e
				raise ValueError(msg)
			
			log.log('Constraining intercept for first h2 estimate to {I}'.format(I=str(intercepts[0])))
			log.log('Constraining intercept for second h2 estimate to {I}'.format(I=str(intercepts[1])))
			log.log('Constraining intercept for gencov estimate to {I}'.format(I=str(intercepts[2])))

		else:
			intercepts = [None, None, None]
		
		rghat = jk.Gencor(betahat1, betahat2, ref_ld, w_ld, N1, N2, M_annot, intercepts,
			args.overlap,	args.rho, args.num_blocks)

		if not args.human_only and n_annot > 1:
			gencov_jknife_ofh = args.out+'.gencov.cov'
			hsq1_jknife_ofh = args.out+'.hsq1.cov'
			hsq2_jknife_ofh = args.out+'.hsq2.cov'	
			_print_cov(rghat.hsq1, hsq1_jknife_ofh, log)
			_print_cov(rghat.hsq2, hsq2_jknife_ofh, log)
			_print_gencov_cov(rghat.gencov, gencov_jknife_ofh, log)
		
		if args.print_delete_vals:
			hsq1_delete_ofh = args.out+'.hsq1.delete_k'
			_print_delete_k(rghat.hsq1, hsq1_delete_ofh, log)
			hsq2_delete_ofh = args.out+'.hsq2.delete_k'
			_print_delete_k(rghat.hsq2, hsq2_delete_ofh, log)
			gencov_delete_ofh = args.out+'.gencov.delete_k'
			_print_delete_k(rghat.gencov, gencov_delete_ofh, log)

		log.log( '\n' )
		log.log( 'Heritability of first phenotype' )
		log.log( '-------------------------------' )
		log.log(rghat.hsq1.summary(ref_ld_colnames) )
		log.log( '\n' )
		log.log( 'Heritability of second phenotype' )
		log.log( '--------------------------------' )
		log.log(rghat.hsq2.summary(ref_ld_colnames) )
		log.log( '\n' )
		log.log( 'Genetic Covariance' )
		log.log( '------------------' )
		log.log(rghat.gencov.summary(ref_ld_colnames) )
		log.log( '\n' )
		log.log( 'Genetic Correlation' )
		log.log( '-------------------' )
		log.log(rghat.summary() )
		
		return [M_annot,rghat]


def freq(args):
	'''
	Computes and prints reference allele frequencies. Identical to plink --freq. In fact,
	use plink --freq instead with .bed files; it's faster. This is useful for .bin files,
	which are a custom LDSC format.
	
	TODO: the MAF computation is inefficient, because it also filters the genotype matrix
	on MAF. It isn't so slow that it really matters, but fix this eventually. 
	
	'''
	log = logger(args.out+'.log')
	if header:
		log.log(header)
		
	if args.bin:
		snp_file, snp_obj = args.bin+'.bim', ps.PlinkBIMFile
		ind_file, ind_obj = args.bin+'.ind', ps.VcfINDFile
		array_file, array_obj = args.bin+'.bin', ld.VcfBINFile
	elif args.bfile:
		snp_file, snp_obj = args.bfile+'.bim', ps.PlinkBIMFile
		ind_file, ind_obj = args.bfile+'.fam', ps.PlinkFAMFile
		array_file, array_obj = args.bfile+'.bed', ld.PlinkBEDFile

	# read bim/snp
	array_snps = snp_obj(snp_file)
	m = len(array_snps.IDList)
	log.log('Read list of {m} SNPs from {f}'.format(m=m, f=snp_file))
	
	# read fam/ind
	array_indivs = ind_obj(ind_file)
	n = len(array_indivs.IDList)	 
	log.log('Read list of {n} individuals from {f}'.format(n=n, f=ind_file))
	
	# read --extract
	if args.extract is not None:
		keep_snps = __filter__(args.extract, 'SNPs', 'include', array_snps)
	else:
		keep_snps = None
	
	# read keep_indivs
	if args.keep:
		keep_indivs = __filter__(args.keep, 'individuals', 'include', array_indivs)
	else:
		keep_indivs = None
	
	# read genotype array
	log.log('Reading genotypes from {fname}'.format(fname=array_file))
	geno_array = array_obj(array_file, n, array_snps, keep_snps=keep_snps,
		keep_indivs=keep_indivs)
	
	frq_df = array_snps.df.ix[:,['CHR', 'SNP', 'A1', 'A2']]
	frq_array = np.zeros(len(frq_df))
	frq_array[geno_array.kept_snps] = geno_array.freq
	frq_df['FRQ'] = frq_array
	out_fname = args.out + '.frq'
	log.log('Writing reference allele frequencies to {O}.gz'.format(O=out_fname))
	frq_df.to_csv(out_fname, sep="\t", header=True, index=False)	
	call(['gzip', '-f', out_fname])


if __name__ == '__main__':
	parser = argparse.ArgumentParser()
		
	# LD Score Estimation Flags
	
	# Input
	parser.add_argument('--bin', default=None, type=str, 
		help='Prefix for binary VCF file')
	parser.add_argument('--bfile', default=None, type=str, 
		help='Prefix for Plink .bed/.bim/.fam file')
	parser.add_argument('--annot', default=None, type=str, 
		help='Filename prefix for annotation file for partitioned LD Score estimation')
	parser.add_argument('--cts-bin', default=None, type=str, 
		help='Filenames for multiplicative cts binned LD Score estimation')
	parser.add_argument('--cts-bin-add', default=None, type=str, 
		help='Filenames for additive cts binned LD Score estimation')
	parser.add_argument('--cts-breaks', default=None, type=str, 
		help='Comma separated list of breaks for --cts-bin. Specify negative numbers with an N instead of a -')
	parser.add_argument('--cts-names', default=None, type=str, 
		help='Comma separated list of column names for --cts-bin.')

	# Filtering / Data Management for LD Score
	parser.add_argument('--extract', default=None, type=str, 
		help='File with SNPs to include in LD Score analysis, one ID per row.')
	parser.add_argument('--keep', default=None, type=str, 
		help='File with individuals to include in LD Score analysis, one ID per row.')
	parser.add_argument('--ld-wind-snps', default=None, type=int,
		help='LD Window in units of SNPs. Can only specify one --ld-wind-* option')
	parser.add_argument('--ld-wind-kb', default=None, type=float,
		help='LD Window in units of kb. Can only specify one --ld-wind-* option')
	parser.add_argument('--ld-wind-cm', default=None, type=float,
		help='LD Window in units of cM. Can only specify one --ld-wind-* option')
	parser.add_argument('--chunk-size', default=50, type=int,
		help='Chunk size for LD Score calculation. Use the default.')

	# Output for LD Score
	#parser.add_argument('--l1', default=False, action='store_true',
	#	help='Estimate l1 w.r.t. sample minor allele.')
	#parser.add_argument('--l1sq', default=False, action='store_true',
	#	help='Estimate l1 ^ 2 w.r.t. sample minor allele.')
	parser.add_argument('--l2', default=False, action='store_true',
		help='Estimate l2. Compatible with both jackknife and non-jackknife.')
	parser.add_argument('--per-allele', default=False, action='store_true',
		help='Estimate per-allele l{N}. Same as --pq-exp 0. ')
	parser.add_argument('--pq-exp', default=None, type=float,
		help='Estimate l{N} with given scale factor. Default -1. Per-allele is equivalent to --pq-exp 1.')
	parser.add_argument('--maf-exp', default=None, type=float,
		help='Estimate l{N} with given MAF scale factor.')
	#parser.add_argument('--l4', default=False, action='store_true',
	#	help='Estimate l4. Only compatible with jackknife.')
	parser.add_argument('--print-snps', default=None, type=str,
		help='Only print LD Scores for these SNPs.')
	#parser.add_argument('--se', action='store_true', 
	#	help='Block jackknife SE? (Warning: somewhat slower)')
	parser.add_argument('--yes-really', default=False, action='store_true',
		help='Yes, I really want to compute whole-chromosome LD Score')
	parser.add_argument('--no-print-annot', default=False, action='store_true',
		help='Do not print the annot matrix produced by --cts-bin.')

	# Summary Statistic Estimation Flags
	
	# Input for sumstats
	parser.add_argument('--intercept', default=None, type=str,
		help='Path to .chisq file with summary statistics for LD Score regression estimation.')
	parser.add_argument('--h2', default=None, type=str,
		help='Path prefix to .chisq file with summary statistics for h2 estimation.')
	parser.add_argument('--rg', default=None, type=str,
		help='Comma-separated list of two prefixes of .chisq/.allele filesets with summary statistics for genetic correlation estimation.')
	parser.add_argument('--ref-ld', default=None, type=str,
		help='Filename prefix for file with reference panel LD Scores.')
	parser.add_argument('--ref-ld-chr', default=None, type=str,
		help='Filename prefix for files with reference panel LD Scores split across 22 chromosomes.')
	parser.add_argument('--ref-ld-fromfile', default=None, type=str,
		help='File with one line per reference ldscore file.')
	parser.add_argument('--ref-ld-fromfile-chr', default=None, type=str,
		help='File with one line per ref-ld-chr prefix.')
	parser.add_argument('--w-ld', default=None, type=str,
		help='Filename prefix for file with LD Scores with sum r^2 taken over SNPs included in the regression.')
	parser.add_argument('--w-ld-chr', default=None, type=str,
		help='Filename prefix for file with LD Scores with sum r^2 taken over SNPs included in the regression, split across 22 chromosomes.')

	parser.add_argument('--invert-anyway', default=False, action='store_true',
		help="Force inversion of ill-conditioned matrices.")
	parser.add_argument('--no-filter-chisq', default=False, action='store_true',
		help='Don\'t remove SNPs with large chi-square.')
	parser.add_argument('--no-intercept', action='store_true',
		help = 'Constrain the regression intercept to be 1.')
	parser.add_argument('--constrain-intercept', action='store', default=False,
		help = 'Constrain the regression intercept to be a fixed value (or a comma-separated list of 3 values for rg estimation).')
	parser.add_argument('--non-negative', action='store_true',
		help = 'Constrain the regression intercept to be 1.')
	parser.add_argument('--aggregate', action='store_true',
		help = 'Use the aggregate estimator.')
	parser.add_argument('--M', default=None, type=str,
		help='# of SNPs (if you don\'t want to use the .l2.M files that came with your .l2.ldscore.gz files)')
	parser.add_argument('--M-file', default=None, type=str,
		help='Alternate .M file (e.g., if you want to use .M_5_50).')
	parser.add_argument('--not-M-5-50', default=False, action='store_true',
		help='Don\'t .M_5-50 file by default.')
		
	# Filtering for sumstats
	parser.add_argument('--info-min', default=None, type=float,
		help='Minimum INFO score for SNPs included in the regression.')
	parser.add_argument('--info-max', default=None, type=float,
		help='Maximum INFO score for SNPs included in the regression.')
	parser.add_argument('--keep-ld', default=None, type=str,
		help='Zero-indexed column numbers of LD Scores to keep for LD Score regression.')
		
	# Optional flags for genetic correlation
	parser.add_argument('--overlap', default=0, type=int,
		help='Number of overlapping samples. Used only for weights in genetic covariance regression.')
	parser.add_argument('--rho', default=0, type=float,
		help='Population correlation between phenotypes. Used only for weights in genetic covariance regression.')
	parser.add_argument('--num-blocks', default=200, type=int,
		help='Number of block jackknife blocks.')
	# Flags for both LD Score estimation and h2/gencor estimation
	parser.add_argument('--out', default='ldsc', type=str,
		help='Output filename prefix')
	parser.add_argument('--maf', default=None, type=float,
		help='Minor allele frequency lower bound. Default is 0')
	parser.add_argument('--human-only', default=False, action='store_true',
		help='Print only the human-readable .log file; do not print machine readable output.')
	# frequency (useful for .bin files)
	parser.add_argument('--freq', default=False, action='store_true',
		help='Compute reference allele frequencies (useful for .bin files).')
	parser.add_argument('--print-delete-vals', default=False, action='store_true',
		help='Print block jackknife delete-k values.')
	args = parser.parse_args()

	defaults = vars(parser.parse_args(''))
	opts = vars(args)
	non_defaults = [x for x in opts.keys() if opts[x] != defaults[x]]
	
	header = MASTHEAD
	header += "\nOptions: \n"
	options = ['--'+x.replace('_','-')+' '+str(opts[x]) for x in non_defaults]
	header += '\n'.join(options).replace('True','').replace('False','')
	header += '\n'

	if args.w_ld:
		args.w_ld = args.w_ld
	elif args.w_ld_chr:
		args.w_ld_chr = args.w_ld_chr
		
	if args.freq:
		if (args.bfile is not None) == (args.bin is not None):
			raise ValueError('Must set exactly one of --bin or --bfile for use with --freq') 
	
		freq(args, header)

	# LD Score estimation
	#elif (args.bin is not None or args.bfile is not None) and (args.l1 or args.l1sq or args.l2 or args.l4):
	#	if np.sum((args.l1, args.l2, args.l1sq, args.l4)) != 1:
	elif (args.bin is not None or args.bfile is not None):
		if args.l2 is None:
			#raise ValueError('Must specify exactly one of --l1, --l1sq, --l2, --l4 for LD estimation.')
			raise ValueError('Must specify --l2 with --bfile.')
		if args.bfile and args.bin:
			raise ValueError('Cannot specify both --bin and --bfile.')
		if args.annot is not None and args.extract is not None:
			raise ValueError('--annot and --extract are currently incompatible.')
		if args.cts_bin is not None and args.extract is not None:
			raise ValueError('--cts-bin and --extract are currently incompatible.')
		if args.annot is not None and args.cts_bin is not None:
			raise ValueError('--annot and --cts-bin are currently incompatible.')	
		if (args.cts_bin is not None or args.cts_bin_add is not None) != (args.cts_breaks is not None):
			raise ValueError('Must set both or neither of --cts-bin and --cts-breaks.')
		if args.per_allele and args.pq_exp is not None:
			raise ValueError('Cannot set both --per-allele and --pq-exp (--per-allele is equivalent to --pq-exp 1).')
		if args.per_allele:
			args.pq_exp = 1
		
		ldscore(args, header)
	
	# Summary statistics
	elif (args.h2 or 
		args.rg or 
		args.intercept or 
		args.rg) and\
		(args.ref_ld or args.ref_ld_chr or args.ref_ld_fromfile or args.ref_ld_fromfile_chr) and\
		(args.w_ld or args.w_ld_chr):
		
		if np.sum(np.array((args.intercept, args.h2, args.rg)).astype(bool)) > 1:	
			raise ValueError('Cannot specify more than one of --h2, --rg, --intercept.')
		if args.ref_ld and args.ref_ld_chr:
			raise ValueError('Cannot specify both --ref-ld and --ref-ld-chr.')
		if args.w_ld and args.w_ld_chr:
			raise ValueError('Cannot specify both --regression-snp-ld and --regression-snp-ld-chr.')
		if args.rho or args.overlap:
			if not args.rg:
				raise ValueError('--rho and --overlap can only be used with --rg.')
			if not (args.rho and args.overlap):
				raise ValueError('Must specify either both or neither of --rho and --overlap.')
					
		sumstats(args, header)
		
		
	# bad flags
	else:
		print header
		print 'Error: no analysis selected.'
		print 'ldsc.py --help describes all options.'