"""
Make quicklook plots MCS tracking.
"""
__author__ = "Zhe.Feng@pnnl.gov"

import sys, os
import subprocess

if __name__ == "__main__":

    # Flag to call Python codes to make plots
    make_plots = True
    make_mp4 = True

    # Specify domain and time
    extent = [-120.0, -70.0, 25.0, 50.0]  # [minlon, maxlon, minlat, maxlat]
    start_date = '2020-07-07T12'
    end_date = '2020-07-11T00'

    run_parallel = 1
    n_workers = 128

    # code_dir = '/global/homes/f/feng045/program/PyFLEXTRKR-dev/Analysis/'
    code_dir = '/global/homes/f/feng045/program/scream/src/'
    config_dir = '/global/homes/f/feng045/program/scream/config/'
    code_name = f'{code_dir}plot_subset_tbpf_mcs_tracks_1panel_demo.py'
    fig_dir = '/global/cfs/cdirs/m1867/zfeng/E3SM/SCREAMv1/cess/conus/quicklooks/'
    out_dir_mp4 = f'{fig_dir}/animations/'
    os.makedirs(out_dir_mp4, exist_ok=True)

    # MCS tracking config files
    config_names = {
        'imerg': 'config_imerg_mcs_tbpf_SCREAM-cell_CONUS.yml',
        'nudged': 'config_SCREAM-Cess_control_nudged.yml',
        'free': 'config_SCREAM-Cess_control_free.yml',
    }

    # Video
    framerate = 2
    vfscale = '1200:-1'

    # Loop over dictionary
    for key, val in config_names.items():
        print(key, val)
        config = f'{config_dir}{val}'
        quicklook_dir = f'{fig_dir}/{key}/'
        figbasename = f'{key}_'

        cmd = f"python {code_name} -c {config} -s {start_date} -e {end_date} " + \
            f" --extent {extent[0]} {extent[1]} {extent[2]} {extent[3]} --output {quicklook_dir} --figbasename {figbasename} " + \
            f" --subset 1 -p {run_parallel}"
        if make_plots == True:
            print(cmd)
            subprocess.run(cmd, shell=True)

        # Make animation
        video_filename = f'{out_dir_mp4}{figbasename}{start_date}_{end_date}.mp4'
        # Make ffmpeg command
        cmd = f"ffmpeg -framerate {framerate} -pattern_type glob -i '{quicklook_dir}{figbasename}*.png' -c:v libx264 -r 10 -crf 20 -pix_fmt yuv420p -vf scale={vfscale} -y {video_filename}"
        if make_mp4 == True:
            print(cmd)
            subprocess.run(cmd, shell=True)
            print(video_filename)