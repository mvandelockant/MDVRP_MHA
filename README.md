# MDVRP solver with Multi-Head Attention, GA, OR-Tools

![newplot](https://user-images.githubusercontent.com/51239551/104798863-88ed3c00-580d-11eb-852c-09c88f2f9afc.png)


## Dependencies

* Python = 3.6
* PyTorch = 1.6
* scipy
* numpy
* plotly (only for plotting)
* matplotlib (only for plotting)
* pandas (only for mean of test score)

## Usage

### train phase

First move to `Torch` dir. 

```
cd Torch
```

Then, generate the pickle file contaning hyperparameter values by running the following command.

```
python config.py
```

you would see the pickle file in `Pkl` dir. now you can start training the model.

```
python train.py -p Pkl/***.pkl
```

### inference phase
Generate test data
  
(GA -> txt file, Torch and Ortools -> json file).

```
python dataclass.py
```

Plot prediction of the pretrained model
```
cd Torch && python plot.py -p Weights/***.pt -t data/***.json -b 128
```
Compare the results 
```
cd GA && python main.py data/***.txt
```
```
cd Ortools && python main.py -p data/***.json
```

## Reference
### DRL_MHA
* https://github.com/Rintarooo/VRP_DRL_MHA
* https://github.com/wouterkool/attention-learn-to-route
* https://github.com/d-eremeev/ADM-VRP
* https://qiita.com/ohtaman/items/0c383da89516d03c3ac0 (written in Japanese)

### Google Or-Tools
* https://github.com/skatsuta/vrp-solver

### GA(Python)
* https://github.com/Lagostra/MDVRP

### GA(C++)
* https://github.com/mathiasaap/Multi-Depot-Routing---Genetic-algorithm
