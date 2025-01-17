"""
Make task list and slurm script (Job Array) to calculate monthly MCS statistics.

Example task list:
python calc_tbpf_mcs_monthly_rainmap.py config.yml 2018 6
python calc_tbpf_mcs_monthly_rainmap.py config.yml 2018 7
python calc_tbpf_mcs_monthly_rainmap.py config.yml 2018 8
...

Each line will be submitted as a slurm job using Job Array.
"""
import sys, os
import textwrap
import subprocess
import pandas as pd

if __name__ == "__main__":

    # Get inputs from command line
    start_date = sys.argv[1]
    end_date = sys.argv[2]
    data_source = sys.argv[3]
    # Examples:
    # start_date = '2018-6'
    # end_date = '2019-5'
    # data_source = 'gpm'

    # region = 'CUS'
    # startlat = 30.0
    # endlat = 49.0
    # startlon = -110.
    # endlon = -80.

    region = 'global'
    startlat = -60.0
    endlat = 60.0
    startlon = -180.
    endlon = 180.

    # Submit job at run time
    submit_job = True

    period = f"{start_date[0:4]}-{end_date[0:4]}"
    # task_type = f"mcs_monthly_rainhov_{data_source}"
    task_type = f"mcs_monthly_rainmap_{data_source}"

    # Python analysis code name
    code_dir = "/global/homes/f/feng045/program/PyFLEXTRKR-dev/Analysis/"
    # code_dir = os.getcwd()
    # python_codename = f"{code_dir}/calc_tbpf_mcs_monthly_rainhov.py"
    # shell_name = f"{code_dir}/run_mcs_monthly_rainhov.sh"
    shell_name = f"{code_dir}/run_mcs_monthly_rainmap.sh"

    # Tracking config file
    config_dir = "/global/homes/f/feng045/program/scream/config/"
    # config_dir = "/global/homes/f/feng045/program/PyFLEXTRKR-dev/"
    config = f"{config_dir}config_{data_source}.yml"

    # Make task and slurm file name
    slurm_dir = os.getcwd()
    task_filename = f"{slurm_dir}/tasklist_{task_type}_{period}.txt"
    slurm_filename = f"{slurm_dir}/slurm.submit_{task_type}_{period}.sh"


    # Make monthly start dates for the tracking period
    start_dates = pd.date_range(f'{start_date}', f'{end_date}', freq='1MS')

    # Create the list of job tasks needed by SLURM...
    task_file = open(task_filename, "w")
    ntasks = 0

    # Create task commands
    for idate in start_dates: 
        if task_type == f"mcs_monthly_rainhov_{data_source}":
            cmd = f"{shell_name} {config} {idate.year} {idate.month} {startlat} {endlat} {startlon} {endlon} {region}"
        elif task_type == f"mcs_monthly_rainmap_{data_source}":
            cmd = f"{shell_name} {config} {idate.year} {idate.month}"
        else:
            print(f"ERROR: unknown type_type: {task_type}")
            sys.exit()
        task_file.write(f"{cmd}\n")
        ntasks += 1
    task_file.close()
    print(task_filename)

    # Create a SLURM submission script for the above task list...
    slurm_file = open(slurm_filename, "w")
    text = f"""\
        #!/bin/bash
        #SBATCH --job-name={period}
        #SBATCH -A m1867
        #SBATCH --time=00:15:00
        #SBATCH -q regular
        #SBATCH -C cpu
        #SBATCH -N 2 -c 128
        #SBATCH --exclusive
        #SBATCH --output=log_{task_type}_{period}.log
        #SBATCH --mail-type=END
        #SBATCH --mail-user=zhe.feng@pnnl.gov

        date

        module load taskfarmer
        export THREADS={ntasks}
        runcommands.sh {task_filename}

        date
        """
    slurm_file.writelines(textwrap.dedent(text))
    slurm_file.close()
    print(slurm_filename)

    # Run command
    if submit_job == True:
        cmd = f"sbatch {slurm_filename}"
        print(cmd)
        subprocess.run(f"{cmd}", shell=True)