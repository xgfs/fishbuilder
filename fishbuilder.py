# Fishbuilder by Jean-Francois Romang [jromang at protonmail.com]

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

import re
import os
import subprocess
import random
import multiprocessing
import tempfile
import numpy
import urllib.request
import zipfile

from deap import algorithms, base, creator, tools

files = ['src/benchmark.cpp','src/bitbase.cpp','src/bitboard.cpp','src/endgame.cpp','src/evaluate.cpp','src/main.cpp',
         'src/material.cpp','src/misc.cpp','src/movegen.cpp','src/movepick.cpp','src/pawns.cpp','src/position.cpp','src/psqt.cpp',
         'src/search.cpp','src/thread.cpp','src/timeman.cpp','src/tt.cpp','src/uci.cpp','src/ucioption.cpp','src/syzygy/tbprobe.cpp']

# https://gcc.gnu.org/onlinedocs/gcc/Optimize-Options.html#Optimize-Options
# Load options from text file in array
options = []
with open("gcc_options.txt", "r") as f:
    data = f.readlines()
    data = [x.strip('\n') for x in data]
    for line in data:
        options.append([None] + line.split(' '))


# Build a Stockfish executable with revelant options
def build(build_options, filename=None):
    if filename is None: filename=tempfile.mktemp()
    default_options='-march=native -m64 -O3 -DNDEBUG -DIS_64BIT -msse -msse3 -mpopcnt -DUSE_POPCNT -DUSE_PEXT -mbmi2'.split(' ')
    subprocess.call(['g++'] + files + default_options + build_options + ['-lpthread', '-o', filename])
    return filename


def profile_build(build_options, filename=None):
    if filename is None: filename = tempfile.mktemp()
    #print("Profile building 1/2")
    build(build_options+['-fprofile-generate', '-lgcov'], filename)
    #print("Bench")
    subprocess.call([filename, 'bench'], stdout=open(os.devnull, 'w'), stderr=subprocess.STDOUT)
    #print("Profile building 2/2")
    build(build_options + ['-fprofile-use', '-lgcov'], filename)
    #print("Done")
    return filename


# Bench the engine with multiple samples
def bench_engine(name, samples):
    command = [name, 'bench']
    file = tempfile.TemporaryFile('r+')
    for n in range(samples):
        subprocess.call(command, stderr=file, stdout=file)
    file.seek(0)
    content = file.readlines()
    bench_log = []
    for line in content:
        mo = re.search('Nodes/second' , line, flags=0)
        if mo is not None:
            num_string = re.sub('[^0-9]','' , mo.string)
            bench_log.append(int(num_string))
    file.close()
    return bench_log


# Translate numbers in text options
def individual_to_parameters(individual):
    parameters = []
    for idx, val in enumerate(individual):
        if options[idx][val] is not None:
            parameters.append(options[idx][val])
    return parameters


# Evaluation function, keep the best sample of the bench
def eval_one_max(individual):
    executable=build(individual_to_parameters(individual))
    if os.path.isfile(executable):
        fitness=max(bench_engine(executable, 3))
        os.remove(executable)
    else:
        fitness = 0
    return [fitness]


# Launch the genetic algorithm loop
def launch_ga(population, generations, executable_dir):
    print("Starting with a population of "+str(population)+" and "+str(generations)+" generations.")
    creator.create("FitnessMax", base.Fitness, weights=(1.0,))
    creator.create("Individual", list, fitness=creator.FitnessMax)
    toolbox = base.Toolbox()

    # Attribute generator
    attributes = []
    for idx, val in enumerate(options):
        toolbox.register("attr_"+str(idx), random.randint, 0, len(val)-1)
        attributes.append(getattr(toolbox, "attr_"+str(idx)))

    toolbox.register("individual", tools.initCycle, creator.Individual, attributes, 1)
    toolbox.register("population", tools.initRepeat, list, toolbox.individual)
    toolbox.register("evaluate", eval_one_max)
    toolbox.register("mate", tools.cxTwoPoint)
    toolbox.register("mutate", tools.mutFlipBit, indpb=0.05)
    toolbox.register("select", tools.selTournament, tournsize=3)
    # Multiprocessing
    pool = multiprocessing.Pool(3)
    toolbox.register("map", pool.map)

    pop = toolbox.population(n=population)
    hof = tools.HallOfFame(1)
    stats = tools.Statistics(lambda ind: ind.fitness.values)
    stats.register("avg", numpy.mean)
    stats.register("std", numpy.std)
    stats.register("min", numpy.min)
    stats.register("max", numpy.max)
    # Launch the evolution algorithm
    pop, log = algorithms.eaSimple(pop, toolbox, cxpb=0.5, mutpb=0.2, ngen=generations, 
                                   stats=stats, halloffame=hof, verbose=True)
    # Display the best individual and save it to disk
    result = '\n'+str(hof)+'\n'+' '.join(individual_to_parameters(hof[0]))+'\n'
    print(result)
    with open(os.path.join(executable_dir, "best_fit.txt"), mode='a') as file:
        file.write(result)
    # Final PGO build with the best parameters
    profile_build(individual_to_parameters(hof[0]), os.path.join(executable_dir, 'stockfish'))


# Individual flag testing
def flag_test(executable_dir):
    # Build base version
    base_executable=profile_build([])
    base_value=max(bench_engine(base_executable, 30))
    print("Base NPS:"+str(base_value))

    with open(os.path.join(executable_dir,'gcc_good.txt')) as f:
        content = f.readlines()
        for line in content:
            flags=line.split(' ')
            for flag in flags:
                flag=flag.strip('\n')
                print("Testing "+flag, end='')
                executable = profile_build([flag])
                flag_value=max(bench_engine(executable, 30))
                percent=flag_value*100/base_value
                print(' '+str(percent)+"% : "+str(flag_value)+"NPS")



if __name__ == "__main__":
    version = '1.02'
    print("Fishbuilder "+version+" by jromang")
    print("WARNING : Intel turbo boost should be DISABLED in the BIOS")

    if not os.path.isfile('Stockfish.zip'):
        # Download latest source
        print("Stockfish.zip not found, downloading lasted source from Github...")
        url="https://github.com/official-stockfish/Stockfish/archive/master.zip"
        with urllib.request.urlopen(url) as response, open('Stockfish.zip', 'wb') as out_file:
            data = response.read()  # a `bytes` object
            out_file.write(data)

    #Current path
    dir_path = os.path.dirname(os.path.realpath(__file__))

    # Unzip source
    src_dir = tempfile.TemporaryDirectory()
    zip_ref = zipfile.ZipFile('Stockfish.zip', 'r')
    zip_ref.extractall(src_dir.name)
    zip_ref.close()
    os.chdir(os.path.join(src_dir.name,'Stockfish-master'))

    launch_ga(100, 50, dir_path)
    #flag_test(dir_path)

