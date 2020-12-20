import torch
import torch.nn as nn

class Env():
	def __init__(self, x, node_embeddings):
		super().__init__()
		"""depot_xy: (batch, n_depot, 2)
			customer_xy: (batch, n_customer, 2)
			--> xy: (batch, n_node, 2); Coordinates of depot + customer nodes
			n_node= n_depot + n_customer
			demand: (batch, n_customer)
			??? --> demand: (batch, n_car, n_customer)
			D(remaining car capacity): (batch, n_car)
			node_embeddings: (batch, n_node, embed_dim)
			--> node_embeddings: (batch, n_car, n_node, embed_dim)

			car_start_node: (batch, n_car); start node index of each car
			car_cur_node: (batch, n_car); current node index of each car
			car_run: (batch, car); distance each car has run 
			pi: (batch, n_car, decoder_step); which index node each car has moved 
			dist_mat: (batch, n_node, n_node); distance matrix
			traversed_nodes: (batch, n_node)
			traversed_customer: (batch, n_customer)
		"""
		self.device = torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
		self.demand = x['demand']
		self.xy = torch.cat([x['depot_xy'], x['customer_xy']], 1)
		self.car_start_node, self.D = x['car_start_node'], x['car_capacity']
		self.car_cur_node = self.car_start_node
		self.pi = self.car_start_node.unsqueeze(-1)

		self.n_depot = x['depot_xy'].size(1)
		self.n_customer = x['customer_xy'].size(1)
		self.n_car = self.car_start_node.size(1)
		self.batch, self.n_node, self.embed_dim = node_embeddings.size()
		self.node_embeddings = node_embeddings[:,None,:,:].repeat(1,self.n_car,1,1)

		# self.demand = demand[:,None,:].repeat(1,self.n_car,1)
				
		self.car_run = torch.zeros((self.batch, self.n_car), dtype = torch.float, device = self.device)

		self.dist_mat = self.build_dist_mat()
		self.mask_depot, self.mask_depot_unused = self.build_depot_mask()
		self.traversed_customer = torch.zeros((self.batch, self.n_customer), dtype = torch.bool, device = self.device)
		
	def build_dist_mat(self):
		xy = self.xy.unsqueeze(1).repeat(1, self.n_node, 1, 1)
		const_xy = self.xy.unsqueeze(2).repeat(1, 1, self.n_node, 1)
		dist_mat = torch.sqrt(((xy - const_xy) ** 2).sum(dim = 3))
		return dist_mat

	def build_depot_mask(self):
		a = torch.arange(self.n_depot, device = self.device).reshape(1, 1, -1).repeat(self.batch, self.n_car, 1)
		b = self.car_start_node[:,:,None].repeat(1, 1, self.n_depot)
		depot_one_hot = (a==b).bool()#.long()
		return depot_one_hot, torch.logical_not(depot_one_hot)


	def get_mask(self, next_node, next_car):
		"""next_node: ([[0],[0],[not 0], ...], (batch, 1), dtype = torch.int32), [0] denotes going to depot
			customer_idx **excludes depot**: (batch, 1), range[0, n_nodes-1] e.g. [[3],[0],[5],[11], ...], [0] denotes 0th customer, not depot
			self.demand **excludes depot**: (batch, n_nodes-1)
			selected_demand: (batch, 1)
			if next node is depot, do not select demand
			self.D: (batch, n_car, 1), D denotes "remaining vehicle capacity"
			self.capacity_over_customer **excludes depot**: (batch, n_car, n_customer)
			visited_customer **excludes depot**: (batch, n_customer, 1)
			is_next_depot: (batch, 1), e.g. [[True], [True], ...]

			mask_depot: (batch, n_car, n_depot) 
			mask_customer: (batch, n_car, n_customer) 
			--> return mask: (batch, n_car, n_node ,1)
		"""
		depot_number = torch.arange(self.n_depot, device = self.device).reshape(1,-1).repeat(self.batch,1)
		# self.is_next_depot = next_node == 0 or next_node == 1
		# is_next_depot = (next_node == depot_number).sum(-1)#.bool()
		is_next_depot = (next_node.repeat(1, self.n_depot) == depot_number).sum(-1)#.bool()
		# next_node: (batch, 1)
		# depot_number: (batch, n_depot)0 or 1 and so on...
		# is_next_depot: (batch), e.g. [[True], [True], ...]
		is_next_customer = torch.logical_not(is_next_depot)

		customer_idx = torch.clamp(next_node - self.n_depot, min = 0., max = self.n_customer)
		# a = torch.arange(self.n_customer, device = self.device).reshape(1,-1).repeat(self.batch,1)
		# b = customer_idx.reshape(self.batch, 1).repeat(1,self.n_customer)
		
		
		new_traversed_customer = torch.eye(self.n_customer, device = self.device)[customer_idx].reshape(self.batch, self.n_customer).bool()
		
		# self.traversed_customer = self.traversed_customer | (new_traversed_customer & is_next_customer)
		self.traversed_customer = self.traversed_customer | (new_traversed_customer * is_next_customer[:,None].repeat(1,self.n_customer))
		# traversed_customer: (batch, n_customer)

		selected_demand = torch.gather(input = self.demand, dim = 1, index = customer_idx)
		# selected_demand = torch.gather(input = self.demand, dim = 1, index = customer_idx)
		
		one_hot = torch.eye(self.n_car, device = self.device)[next_car].reshape(self.batch, self.n_car)
		
		# car_used_demand = is_next_customer.long() * one_hot * selected_demand
		car_used_demand = is_next_customer[:,None].repeat(1,self.n_car) * one_hot * selected_demand
		"""is_next_customer: (batch, 1)
			one_hot: (batch, n_car)
			selected_demand: (batch)
			car_used_demand: (batch, n_car)
		"""
		self.D -= car_used_demand
		# self.D = torch.clamp(self.D, min = 0.)
		# self.D[:,next_car] = max(0., self.D[:,next_car] - selected_demand * (1.0 - self.is_next_depot.float()))
		
		capacity_over_customer = self.demand[:,None,:].repeat(1,self.n_car,1) > self.D[:,:,None].repeat(1,1,self.n_customer)
		mask_customer = capacity_over_customer | self.traversed_customer[:,None,:].repeat(1,self.n_car,1)
		# mask_depot = self.is_next_depot[:,None].repeat(1,self.n_car) & ((mask_customer == False).long().sum(dim = -1) > 0)
		# mask_depot = (self.car_cur_node == self.car_start_node) & ((mask_customer == False).long().sum(dim = -1) > 0)
		mask_depot = (self.car_cur_node == self.car_start_node) & ((mask_customer == False).long().sum(dim = 2).sum(dim = 1)[:,None].repeat(1,self.n_car) > 0)
		# one_hot = torch.eye(self.n_node, device = self.device)[self.car_start_node]
		# one_hot: (batch, n_car, n_node)

		# mask_depot = self.mask_depot.bool() & mask_depot.bool().reshape(self.batch, self.n_car, 1).repeat(1,1,self.n_depot)
		mask_depot = self.mask_depot & mask_depot.bool().reshape(self.batch, self.n_car, 1).repeat(1,1,self.n_depot)
		
		mask_depot = self.mask_depot_unused | mask_depot
		""" mask_depot = True
			==> We cannot choose depot in the next step if 1) next destination is depot or 2) there is a node which has not been visited yet
		"""
		mask = torch.cat([mask_depot, mask_customer], dim = -1).unsqueeze(-1)
		# print(mask[0].long())
		return mask
	
	def _get_step(self, next_node, next_car):
		"""next_node **includes depot** : (batch, 1) int, range[0, n_nodes-1]
			--> one_hot: (batch, 1, n_nodes)
			node_embeddings: (batch, n_nodes, embed_dim)
			demand: (batch, n_nodes-1)
			--> if the customer node is visited, demand goes to 0 
			
			each_car_idx: (batch, n_car, 1, embed_dim)
			node_embeddings: (batch, n_car, n_node, embed_dim)
			--> prev_embedding; node embeddings where car is located

			return 
			D: (batch, n_car, 1, 1)
			prev_embedding: (batch, n_car, 1, embed)
			--> 1. step_context: (batch, n_car, 1, embed_dim+1)
			2. mask: (batch, n_car, n_node ,1)
		"""
		self.update_node_path(next_node, next_car)
		self.update_car_distance()
		mask = self.get_mask(next_node, next_car)
		# self.demand = self.demand.masked_fill(self.traversed_customer[:,:,0] == True, 0.0)
		
		each_car_idx = self.car_cur_node[:,:,None,None].repeat(1,1,1,self.embed_dim)		
		prev_embeddings = torch.gather(input = self.node_embeddings, dim = 2, index = each_car_idx)

		step_context = torch.cat([prev_embeddings, self.D[:,:,None,None]], dim = -1)
		return mask, step_context

	def _create_t1(self):
		"""return
			mask: (batch, n_car, n_node ,1)
			initial_context: (batch, n_car, 1, embed+1)
		"""
		mask_t1 = self.create_mask_t1()
		step_context_t1 = self.create_context_t1()		
		return mask_t1, step_context_t1

	def create_mask_t1(self):
		"""mask_depot: (batch, n_car, n_depot) 
			mask_customer: (batch, n_car, n_customer) 
			--> return mask: (batch, n_car, n_node ,1)
		"""
		mask_depot_t1 = self.mask_depot | self.mask_depot_unused
		mask_customer_t1 = self.traversed_customer[:,None,:].repeat(1,self.n_car,1)
		mask_t1 = torch.cat([mask_depot_t1, mask_customer_t1], dim = -1).unsqueeze(-1)
		return mask_t1
		
	def create_context_t1(self):
		"""car_start_node: (batch, n_car); from which node car start
			depot_idx: (batch, n_car, 1, embed_dim)
			node_embeddings: (batch, n_car, n_node, embed_dim)
			D: (batch, n_car)
			-->　D: (batch, n_car, 1, 1)
			depot_embedding: (batch, n_car, 1, embed)

			return initial_context: (batch, n_car, 1, embed+1)
		"""
		# depot_idx = torch.zeros([self.batch, 1], dtype = torch.long).to(self.device)# long == int64
		depot_idx = self.car_start_node[:,:,None,None].repeat(1,1,1,self.embed_dim)
		depot_embedding = torch.gather(input = self.node_embeddings, dim = 2, index = depot_idx)
		# depot_embedding = torch.gather(input = self.node_embeddings, dim = 1, index = depot_idx[:,:,None].expand(self.batch,1,self.embed_dim))
		# https://medium.com/analytics-vidhya/understanding-indexing-with-pytorch-gather-33717a84ebc4
		
		# return torch.cat([depot_embedding, self.D[:,:,None,None].repeat(1,1,1,self.embed_dim)], dim = 2)
		return torch.cat([depot_embedding, self.D[:,:,None,None]], dim = -1)

	def update_node_path(self, next_node, next_car):
		# car_node: (batch, n_car)
		# pi: (batch, n_car, decoder_step)
		self.car_prev_node = self.car_cur_node
		a = torch.arange(self.n_car, device = self.device).reshape(1, -1).repeat(self.batch, 1)
		b = next_car.reshape(self.batch, 1).repeat(1, self.n_car)
		mask_car = (a == b).long()
		new_node = next_node.reshape(self.batch, 1).repeat(1, self.n_car)
		self.car_cur_node = mask_car * new_node + (1 - mask_car) * self.car_cur_node
		self.pi = torch.cat([self.pi, self.car_cur_node.unsqueeze(-1)], dim = -1)

	def update_car_distance(self):
		prev_node_dist_vec = torch.gather(input = self.dist_mat, dim = 1, index = self.car_prev_node[:,:,None].repeat(1,1,self.n_node))
		# dist = torch.gather(input = prev_node_dist_vec, dim = 2, index = self.car_cur_node[:,None,:].repeat(1,self.n_car,1))
		dist = torch.gather(input = prev_node_dist_vec, dim = 2, index = self.car_cur_node[:,:,None])
		self.car_run += dist.squeeze(-1)
		# print(self.car_run[0])

	def return_depot_all_car(self):
		self.pi = torch.cat([self.pi, self.car_start_node.unsqueeze(-1)], dim = -1)
		self.car_prev_node = self.car_cur_node
		self.car_cur_node = self.car_start_node
		self.update_car_distance()

	def get_log_likelihood(self, _log_p, _idx):
		"""_log_p: (batch, decode_step, n_car * n_node)
			_idx: (batch, decode_step, 1), selected index
		"""
		log_p = torch.gather(input = _log_p, dim = 2, index = _idx)
		return log_p.squeeze(-1).sum(dim = 1)

class Sampler(nn.Module):
	"""args; logits: (batch, n_car * n_nodes)
		return; next_node: (batch, 1)
		TopKSampler --> greedy; sample one with biggest probability
		CategoricalSampler --> sampling; randomly sample one from possible distribution based on probability
	"""
	def __init__(self, n_samples = 1, **kwargs):
		super().__init__(**kwargs)
		self.n_samples = n_samples
		
class TopKSampler(Sampler):
	def forward(self, logits):
		return torch.topk(logits, self.n_samples, dim = 1)[1]
		# torch.argmax(logits, dim = 1).unsqueeze(-1)

class CategoricalSampler(Sampler):
	def forward(self, logits):
		return torch.multinomial(logits.exp(), self.n_samples)