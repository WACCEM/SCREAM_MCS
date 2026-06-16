#!/bin/bash
# Wrapper shell script that runs the Python code for TaskFarmer
source activate /global/common/software/m1867/python/pyflex26.3
python /global/homes/f/feng045/program/scream/scripts/calc_mergir_missing_data.py $1 $2
