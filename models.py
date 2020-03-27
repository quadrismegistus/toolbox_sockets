import logging,time,os
import numpy as np
import db as DB
from tqdm import tqdm
from app_config import *

#  global variables for storage
fn2M = {}
fn2voc={} 





class Embedding(object): 

	def __init__(self,model_id,model_fn,model_periods=[]):
		self.fn = model_fn
		self.periods=model_periods
		self.id=model_id
		self.log=lambda x: print(x+'\n') #logging.info
		self.progress=logging.info


	## Three methods of storage/calculation
	
	## 1) Gensim
	@property
	def gensim(self):
		import gensim
		if not hasattr(self,'_gensim'):
			now=time.time()
			self.log('generating model from vectors stored in db: '+self.fn)
			self._gensim = gensim.models.KeyedVectors(vector_size=300)
			all_words,all_vecs = self.get_all_word_vecs()
			self._gensim.add(all_words,all_vecs)
			tdist=round(time.time()-now,1)
			self.log('done loading model in %ss' % tdist)
		return self._gensim

	## 2) VecDB
	@property
	def db(self):
		if not hasattr(self,'_db'): self._db=DB.get_vecdb(self.id)
		return self._db

	## 3) DistNet
	@property
	def distdb(self):
		if not hasattr(self,'_distdb'): self._distdb=DB.get_distdb(self.id)
		return self._distdb

	@property
	def distnet_fn(self):
		if hasattr(self,'fn_distnet'): return self.fn_distnet
		return os.path.splitext(self.fn)[0]+'.distnet.txt'

	@property
	def distnet(self):
		self.log('building network...')
		G=nx.Graph()
		for word in tqdm(all_words):
			row = dfdist.loc[word].sort_values().iloc[1:n_top+1]
			sim_rank=0
			for word2,result in zip(row.index,row):
				sim_rank+=1
				G.add_edge(word,word2,weight=result,sim_rank=sim_rank)
		
		#self.log('saving network')

	## DATA GENERATION

	def build_vecdb(self,max_num_vecs=MAX_NUM_VECS_TO_STORE):
		with open(self.fn) as f:
			for i,ln in enumerate(tqdm(f)):
				if i==0: continue
				if i>max_num_vecs: break
				lndat=ln.split()
				word=lndat[0]
				wordvecs=[float(x) for x in lndat[1:]]
				self.db.insert({'word':word,'vecs':wordvecs})

	


	def build_distdb(self,n_top=DEFAULT_N_TOP,n_vecs=MAX_NUM_VECS_TO_STORE):
		self.log('BUILDING DISTANCE DATABASE')
		
		all_words,all_vecs=self.get_all_word_vecs()
		vecsM = np.array(all_vecs[:n_vecs])
		vocab=all_words[:n_vecs]
		print('vecs shape',vecsM.shape)

		# scikit?
		import time
		now=time.time()
		from sklearn.metrics import pairwise_distances
		arr = pairwise_distances(vecsM, metric='cosine',n_jobs=4)
		tdist=round(time.time()-now,1)
		print('done computing %s vecs in %ss' % (n_vecs,tdist))

		# pandas?
		now=time.time()
		import pandas as pd
		dfdist=pd.DataFrame(arr,index=vocab,columns=vocab)
		tdist=round(time.time()-now,1)
		print('done computing pandas in %ss' % tdist)

		# insert?
		now=time.time()
		batch=[]
		for word in tqdm(vocab):
			row = dfdist.loc[word].sort_values().iloc[1:n_top+1]
			sim_rank=0
			for word2,result in zip(row.index,row):
				sim_rank+=1
				odx={'source':word,'target':word2,'weight':1-result,'sim_rank':sim_rank}
				batch+=[odx]
				if len(batch)>1000:
					self.distdb.insert_many(batch)
					#break
					batch=[]
			#break
		if len(batch)>0: self.distdb.insert_many(batch)
		tdist=round(time.time()-now,1)
		print('done building and inserting results in %ss' % tdist)



	## DATA ACCESS


	### GETTING VECTORS

	def get_vector_from_db(self,vecname):
		# print('Q:',vecname)
		res=self.db.find_one({'word':vecname})
		if res==None: return res
		return np.array(res['vecs'])

	def get_all_word_vecs(self):
		all_words=[]
		all_vecs=[]
		for d in tqdm(self.db.find()):
			try:
				all_words.append(d['word'])
				all_vecs.append(d['vecs'])
			except:
				pass
		return(all_words,all_vecs)


	def get_vector(self, word_or_formula, opts={}):
		# print('get_vector_opts',opts)
		formula_str=word_or_formula
		formula_str_q=formula_str.strip().replace('[','').replace(']','')
		self.log('looking for: '+formula_str_q)
		
		cached_formula_vec=self.get_vector_from_db(formula_str_q)
		if cached_formula_vec is not None: 
			self.log(f'\tfound cache of {formula_str_q}, returning')
			return cached_formula_vec

		self.log('\tdid not find cache, must be either a formula or alternatively dated')
		words_involved = split_words_only(word_or_formula)
		word2vecs = {}
		self.log('\tsplitting into components:' + ', '.join(words_involved))
		uncached_vecs=[]
	
		for w in words_involved:
			self.log(f'\t\tlooking for cache of word component: {w}')
			cached_word_vec = self.get_vector_from_db(w)
			if cached_word_vec is not None:
				self.log(f'\t\t\tfound cache of {w}, adding to component word2vecs dictionary')
				word2vecs[w]=cached_word_vec
			else:
				self.log(f'\t\t\tdid not find cache of "{w}", must be alt-dated')

				#  still no cache?
				#  maybe it has no period and we need to periodize
				#  try an average?
				
				word_vecs_to_avg = []
				w_periodized = periodize([w],self.periods)
				self.log('\t\t\t\treperiodized string into {0}'.format(', '.join(w_periodized)))
				for word_period in w_periodized:
					self.log(f'\t\t\t\tlooking for cache of word_period component {word_period}')
					cached_word_period_vec = self.get_vector_from_db(word_period)
					if cached_word_period_vec is not None:
						self.log(f'\t\t\t\t\tfound cache of "{word_period}", adding to word_vecs_to_avg')
						word_vecs_to_avg.append(cached_word_period_vec)
				# print('w?',word_vecs_to_avg)
				self.log('\t\t\t\taveraging {0} vectors for {1}'.format(len(word_vecs_to_avg), w))
				word_vec_avg = np.mean(word_vecs_to_avg,0) # column wise
				word2vecs[w]=word_vec_avg
		
		self.log('\treturning vector result for original formula: '+formula_str_q)
		vec_res = solve_vectors(formula_str_q,word2vecs)
		return vec_res

	def get_vectors(self,words_or_formulae):
		name2vecs = {}
		for word_or_formula in words_or_formulae:
			name2vecs[word_or_formula] = self.get_vector(word_or_formula)
			self.log('got vector for:'+word_or_formula)
		return name2vecs

	





	## GETTING SIMILARITY CALCULATIONS


	def get_most_similar(self,words,periods=None,combine_periods=DEFAULT_COMBINED_PERIODS):
		if periods is None: periods=self.periods
		if combine_periods in {'simultaneous','diachronic'}:
			words=periodize(words, periods)
		
		self.log('input split into: ' + ', '.join(words))
		name2vec = self.get_vectors(words)
		self.log('got name2vec with %s vectors' % len(name2vec))
		most_similar_data = self.get_most_similar_by_vector(name2vec)
		return most_similar_data


	def get_most_similar_by_vector(self,name2vec,**args):
		return self.get_most_similar_by_vector_by_gensim(name2vec,**args)

	def get_most_similar_by_vector_by_gensim(self,name2vec,n_top=DEFAULT_N_TOP,combine_periods=DEFAULT_COMBINED_PERIODS):
		all_sims=[]
		for name,vec in sorted(name2vec.items()):

			name_sims = self.gensim.wv.similar_by_vector(vec,topn=n_top+1)
			self.log('got back from gensim for similar_by_vector: '+str(name_sims))

			new_name_sims=[]
			for xi,x in enumerate(name_sims[1:]):
				print('x',x)
				match=x[0]
				csim=x[1]
				new_sim_d={}
				new_sim_d['id']=id1=name
				new_sim_d['id2']=id2=match
				worddat1=deperiodize_str(id1)
				worddat2=deperiodize_str(id2)
				new_sim_d['word'] = wordname1 = worddat1[0]
				new_sim_d['word2'] =wordname2 = worddat2[0]
				new_sim_d['period'] = period1 = worddat1[1]
				new_sim_d['period2'] = period2 = worddat2[1]
				new_sim_d['csim']=csim
				new_sim_d['csim_rank']=xi+1

				# combine across periods?
				new_name_sims.append(new_sim_d)


				# if((period1!=undefined) & (opts['combine_periods']=='diachronic') & (period2!=period1)) {
				# 	#  skip because let's not compare across periods in that case
				# 	#  print('yep!!')
				# } else {

				# 	#  print('new_sim_d!?',new_sim_d)
				# 	if((!(id2 in name2vec)) &(!(wordname2 in name2vec)) &(unique_words.size<n_top)) {
				# 		#  if we either want all periods, or periods wanted includes this one
				# 		if(periods==undefined | (periods.includes(period2))) {
				# 			#  start a new dictionary
				# 			name_sims.push(new_sim_d)


				# 			#  print('new_sim_d',new_sim_d)
				# 			if(!(unique_words.has(wordname2))) {
				# 				unique_words.add(wordname2)
				# 			}
						
				# 		}
				# 	}
				# }
				# })

			#  name_sims average?
			if(combine_periods=='average'):
				new_name_sims=average_periods(new_name_sims,val_key='csim',word_key='id2',period_key='period2')


			all_sims.extend(new_name_sims)
		
		self.log('collecting '+str(len(all_sims))+' cosine sims')
		return all_sims
	

# 	#  self.get_most_similar_by_vector = function(opts) {
# 	#  	print('OPTS!','get_most_similar_by_vector',opts)
# 	#  	var name2vec=opts['name2vec']
# 	#  	var n_top=opts['n_top']
# 	#  	var periods = opts['periods']
# 	#  	if(n_top==undefined) { n_top = DEFAULT_N_SIMILAR }


# 	#  	all_sims = []
# 	#  	n_names = 0
# 	#  	for(var name in name2vec) { n_names++ }
# 	#  	i_names=0


# 	#  	for(var name in name2vec) {
# 	#  		#  self.progress(i_names/n_names, opts)
# 	#  		i_names++
# 	#  		self.log('getting '+ n_top +' nearest word vectors to: ' + name)
# 	#  		vec=name2vec[name]
# 	#  		# print('vec!',name,vec)
# 	#  		sims = this.M.getNearestWords(vec, (n_top+1)*5)
# 	#  		#  sims = this.M.getNearestWords(vec, (n_top+1)*2)
# 	#  		name_sims=[]
# 	#  		unique_words=new Set()
# 	#  		sims.forEach(function(sim_d) {
# 	#  			new_sim_d={}
# 	#  			new_sim_d['id']=id1=name
# 	#  			new_sim_d['id2']=id2=sim_d['word']
# 	#  			worddat1=deperiodize_str(id1)
# 	#  			worddat2=deperiodize_str(id2)
# 	#  			new_sim_d['word'] = wordname1 = worddat1[0]
# 	#  			new_sim_d['word2'] =wordname2 = worddat2[0]
# 	#  			new_sim_d['period'] = period1 = worddat1[1]
# 	#  			new_sim_d['period2'] = period2 = worddat2[1]
# 	#  			new_sim_d['csim']=sim_d['dist']
# 	#  			if((period1!=undefined) & (opts['combine_periods']=='diachronic') & (period2!=period1)) {
# 	#  				#  skip because let's not compare across periods in that case
# 	#  				#  print('yep!!')
# 	#  			} else {

# 	#  				#  print('new_sim_d!?',new_sim_d)
# 	#  				if((!(id2 in name2vec)) &(!(wordname2 in name2vec)) &(unique_words.size<n_top)) {
# 	#  					#  if we either want all periods, or periods wanted includes this one
# 	#  					if(periods==undefined | (periods.includes(period2))) {
# 	#  						#  start a new dictionary
# 	#  						name_sims.push(new_sim_d)


# 	#  						#  print('new_sim_d',new_sim_d)
# 	#  						if(!(unique_words.has(wordname2))) {
# 	#  							unique_words.add(wordname2)
# 	#  						}
						
# 	#  					}
# 	#  				}
# 	#  			}
# 	#  		})

# 	#  		#  final average
# 	#  		if(opts['combine_periods']=='average') { name_sims=average_periods(name_sims,val_key='csim',word_key='word2',period_key='period2') }

# 	#  		all_sims.push(...name_sims)
# 	#  	}
# 	#  	#  print('all_sims',all_sims.length)
# 	#  	return all_sims
# 	#  }

# 	self.get_expanded_wordset = function(opts) {
# 		print('get_expanded_wordset()',opts)

# 		var expand_n=opts['expand_n']
# 		if(expand_n==undefined) { expand_n = DEFAULT_EXPAND_N }
# 		name2vecs = self.get_vectors(opts)
# 		log('retrieved vector data for existing words')
	  
# 		vecs = dict_values(name2vecs)
# 		sumvec = math.add(...vecs)
# 		words_already=opts['words']
# 		log('computed vector sum of existing words')

# 		opts['name2vec'] = {'sumvec':sumvec}
# 		most_similar_data = self.get_most_similar_by_vector(opts)
# 		log('found '+most_similar_data.length+' nearest words to sum vector')

# 		var matches = []
# 		most_similar_data.forEach(function(d) {
# 		   #  wordx=d.word2
# 		  #  don't include period anymore: should be an option?
# 		  wordx=d.word2.split('_')[0]
# 		  if(!words_already.includes(wordx)) {
			
			
# 			words_already.push(wordx)
# 			if(matches.length < expand_n) {
# 			  matches.push(wordx)
# 			}
# 		  }
# 		})
# 		return matches
# 	}

# 	#  self.progress(1.0,opts)
# 	return Model
# }






# #  Get vocabulary from a vocab fn
# function get_vocab(fn) {
# 	return new Promise(function(resolve,reject) {
		
# 		fs.readFile(fn, "UTF8", function(err, data) {
# 			var all_vocab =[]
# 			vtxt=data
# 			var all_vocab=[]
# 			#  print(fn)
# 			lines=vtxt.split('\n')
# 			lines.forEach(function(line) {
# 				#  print(line)
# 				word=line.split(' ')[0]
# 				# print(word)
# 				all_vocab.push(word)
# 			});
# 			#  print('all_vocab',all_vocab)
# 			resolve(all_vocab)
# 		})
		
# 	});
# }


# #  get model (as a promise)
# async function get_model(w2v_fn = DEFAULT_W2V_FN) { 
# 	#  print('>> loading w2v_fn:',w2v_fn)
# 	var voc_fn=w2v_fn.replace('.txt','.vocab.txt')
# 	var model_promise
# 	var vocab_promise
# 	if(w2v_fn in fn2M) {
# 		print('>> RESTORING FROM CACHE:',w2v_fn)
# 		vocab_promise = new Promise(function(res,rej) { res(fn2voc[w2v_fn]) })
# 		model_promise = new Promise(function(res,rej) { res(fn2M[w2v_fn]) })
# 	} else {
# 		model_promise = new Promise(function(res,rej) { 
# 			w2v.loadModel(w2v_fn,function(err,model) {
# 				fn2M[w2v_fn]=model
# 				# print('loaded',w2v_fn,model)
# 				res(model)
# 			})
# 		})
# 		vocab_promise = new Promise(function(res,rej) { 
# 			get_vocab(voc_fn).then(function(all_vocab) {
# 				fn2voc[w2v_fn]=all_vocab
# 				res(all_vocab)
# 			})
# 		})
# 	}
# 	M = await model_promise
# 	Voc = await vocab_promise
# 	# print("mvoc2",M,Voc)
# 	return [M,Voc]
# }


# #  function opts2model_fn(opts) {
# #  	print(opts,'??????')
# #  	print('model_id: ',opts['model_id'])
# #  	res=W2V_MODELS[opts['model_id']]
# #  	print('model res:',res)
# #  	return res
# #  }








def split_words_only(_words):
	#return _words.replace('[','').replace(']','').replace(' ','').replace(',',' ').split()
	return [w for w in split_words_keep_punct(_words) if w and w[0].isalpha()]
	

# function split_words(_words) {
# 	print('split_words',_words)
# 	_words=_words.replace('\r\n',',').replace('\r',',').replace('\n',',')
# 	try {
# 		_words_l0 = _words.split(',')
# 	} catch(TypeError) {
# 		return [];
# 	}
# 	_words_l = []
# 	for(wii=0; wii<_words_l0.length; wii++) {
# 		_words_l.push(_words_l0[wii].trim());
# 	}
# 	return _words_l;
# }

def split_words_keep_punct(_words):
	import re
	return re.findall(r"[\w']+|[.,!?;\-\+\/\*]", _words)

# function isAlpha(str) {
#   return /^[a-zA-Z]+$/.test(str);
# }


# function reformat_formula_str(_words) {
# 	var _words=_words.replace(' ','')
# 	return _words
# }

# function compute_arrays(x, y, operator) {
# 	# print('computing array with operator',operator)
# 	# print(x,operator,y)


# 	if(operator=='+') { return math.add(x,y) }
# 	if(operator=='-') { return math.subtract(x,y) }
# 	if(operator=='*') { return math.multiply(x,y) }
# 	if(operator=='/') { return math.divide(x,y) }
# }

# function vector_add(x, y) { return math.add(x,y) }
# function vector_subtract(x, y) { return math.subtract(x,y) }
# function vector_divide(x, y) { return math.divide(x,y) }
# function vector_multiply(x, y) { return math.multiply(x,y) }


def solve_vectors(formula, var2val={}):
	formula=formula.replace('[','').replace(']','')

	import expression
	parser = expression.Expression_Parser(variables=var2val)
	return parser.parse(formula)


# function compute_tree(tree,var2val={}) {
# 	var arr_left=undefined;
# 	var arr_right=undefined;
# 	var op=undefined;
# 	var new_val=undefined;
# 	#  if branches
# 	if (tree.left) { 
# 		#  print('found split in tree:',tree.left,tree.operator,tree.right)
# 		arr_left = compute_tree(tree.left,var2val)
# 		op = tree.operator
# 		arr_right = compute_tree(tree.right,var2val)
# 		new_val = compute_arrays(arr_left,arr_right,op)
# 		#  print('computation result ',arr_left[0],op,arr_right[0],'= ',new_val[0])
# 		return new_val;
# 	} else if (tree.value) {
# 		#  print('found a value in tree',tree.value)
# 		return tree.value;
# 	} else {
# 		#  print('found a variable in tree',tree.name)
# 		new_val = var2val[tree.name]
# 		#  print('found a new_val of',new_val) # .islice(0,5))
# 		# print('new_val',new_val)
# 		return new_val;
# 	}
# }

# function dict_values(vector_data) {
# 	var vecs = []
# 	for(var name in vector_data) { 
# 		vec = vector_data[name]
# 		if(vec!=undefined) { 
# 			vecs.push(vec)
# 		}
# 	}
# 	return vecs
# }



# #  Umap
# function get_umap_from_vector_data(name2vec) {
# 	print(name2vec)

# 	data = []
# 	names = []
# 	for(name in name2vec) {
# 		data.push(name2vec[name])
# 		names.push(name)
# 	}
# 	print('names',names)

# 	umapjs = require('umap-js')

# 	const umap = new umapjs.UMAP({nComponents: 2,nEpochs: 400,nNeighbors: 3,});
# 	const embedding = umap.fit(data)

# 	out_ld = []

# 	embedding.forEach(function(erow,i) {
# 		name=names[i]
# 		word_period=deperiodize_str(name)
# 		word=word_period[0]
# 		period=word_period[1]

# 		out_d={}
# 		out_d['name']=names[i]
# 		out_d['word']=word
# 		out_d['period']=period
# 		out_d['umap_V1']=erow[0]
# 		out_d['umap_V2']=erow[1]
# 		out_ld.push(out_d)

# 		print(out_d)
# 	})


# 	return out_ld
# }



# #  M = new Model(DEFAULT_W2V_FN)
# #  M = gen_model(DEFAULT_W2V_FN)
# #  print('Mfn',M.fn)

# #  gen_model(DEFAULT_W2V_FN).then(function(M) {
# #  	print('M??',M)
# #  	print('Mfn2',M.fn)
# #  	print("Mvoclength",M.num_words())
# 	#  print('Mvec11',M.get_vectors(['word_1950', 'word_1950 + word_1900', 'value_1800']))
# 	#  print('Mvec22',M.get_most_similar('value_1800,value_1800-value_1950'))
# 	#  print('MM',M.M)
# #  })

# #  print('MVOC',M.vocab)


def periodize(words,periods):
	word_periods = []
	# print('periodize',words,periods)

	for w in words:
		if '_' in w and w.split('_')[1][0].isdigit(): 
			word_periods.append(w)
			continue  # if already period keep going
		
		word_pieces = split_words_keep_punct(w)
		for p in periods:
			# print(p,'...')
			if len(word_pieces)==1:
				word_period=w+'_'+p
			else:
				word_period_l = []
				for wpiece in word_pieces:
					if wpiece.isalpha():
							word_period_l.append(wpiece+'_'+p)
					else:
						word_period_l.append(wpiece)
				word_period=''.join(word_period_l)

			word_periods.append(word_period)
		# else:
			# word_periods.append(w)
	#print('PERIODIZED:',words,'-->',word_periods)
	return word_periods


def get_period_from(wordstr):
	if '_' in wordstr:
		period=wordsstr.split('_')[-1]
		if period[0].isdigit():
			return period
	return ''


def deperiodize_str(wordstr):
	new_word_pieces=[]
	word_pieces = split_words_keep_punct(wordstr)
	periods=[]
	for wpiece in word_pieces:
		if '_' not in wpiece:
			new_word_pieces.append(wpiece)
		else:
			word=wpiece.split('_')[0]
			period=wpiece.split('_')[1]
			periods.append(period)
			new_word_pieces.append(word)
	return (''.join(new_word_pieces), periods[0])



# function average_periods(word_ld,val_key='csim',word_key='word',period_key='period',periods=undefined) {
# 	# create word2ld
# 	word2vals = {}
# 	word2eg = {}
# 	word_ld.forEach(function(word_d) {
# 		word=word_d[word_key]

# 		var ok = true
# 		if(periods!=undefined) {
# 			period=word_d[period_key]
# 			if(!periods.includes(period)) {
# 				ok=false
# 			}
# 		}

# 		if(ok) {
# 			if(!(word in word2vals)) { word2vals[word]=[]; word2eg[word]=word_d }
# 			word2vals[word].push(parseFloat(word_d[val_key]))
# 		}
# 	})

# 	word_old=[]
# 	for(word in word2vals) {
# 		word_vals = word2vals[word]
# 		word_vals_avg = math.mean(word_vals)
# 		word_od = {}
# 		for(k in word2eg[word]) { word_od[k]=word2eg[word][k] }
# 		word_od[val_key]=word_vals_avg
# 		word_old.push(word_od)
# 	}

# 	return word_old
# }


# async function get_orig_vocab(fn) {

# 	vocab_promise=new Promise(function(resolve,reject) { 

# 		var line_num=0
# 		var line_words=[]
# 		lineReader.eachLine(fn, function(line, last) {
# 			#  print('>>>',line_num,line.slice(0,5),last)
# 			if((line_num > 0) & (line!='')) {
# 				line_word=line.split(' ')[0]
# 				line_words.push(line_word)
# 				#  print(line_word)
# 			}
# 			line_num++

# 			if(last) {
# 				resolve(line_words)
# 			}
# 		})
		
# 	})
# 	vocab_result = await vocab_promise
# 	#  print('vocab_result!',vocab_result)
# 	return vocab_result
# }




# exports.with_model = with_model
# exports.W2V_MODELS = W2V_MODELS
# exports.periodize = periodize
# exports.deperiodize_str = deperiodize_str
# exports.get_umap_from_vector_data=get_umap_from_vector_data











if __name__=='__main__':
	e = Embedding(DEFAULT_W2V_MODEL,DEFAULT_W2V_FN,DEFAULT_PERIODS)
	e.build_vecdb()
	e.build_distdb()




	
	# print(e.get_vector('value_1800'))
	# print(e.get_vector('value'))
	# print(e.get_vector('value-importance'))
	# print(e.get_vector('value_1800-importance_1950'))


	# print(e.get_vectors(['value_1800','importance_1950','value']))


	# print(e.get_most_similar(['virtue','vice']))
	# print(e.get_most_similar(['virtue','vice']))
	# print(e.get_most_similar(['virtue','vice']))
	# print(e.get_most_similar(['virtue','vice']))
	# print(e.get_most_similar(['virtue','vice']))


	