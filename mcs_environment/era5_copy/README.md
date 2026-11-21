# Copy ERA5 from CFS to scratch with Globus (step by step)

ERA5 lives on CFS (`/global/cfs/projectdirs/m3522/cmip6/ERA5`), which is not made for the many parallel reads of the extraction jobs. Copy what is needed to
`/pscratch/sd/w/wcmca1/ERA5` first. This follows NERSC's Globus guidance (https://docs.nersc.gov/services/globus/): the Globus command-line tools from the module
`globus-tools`, the helper `transfer_files.py` with the NERSC DTN (and `generate_token.py` for its login), and `check_transfers.py` to follow the tasks. You run it; the files are
written as your own user (feng045, they count toward your scratch quota: see step 7), because a transfer as a collaboration account needs a dedicated Globus endpoint that NERSC sets up on request.

**What is copied** (whole files, all 37 levels; Globus cannot subset levels): pressure-level Q, R, W (daily files, about 4.5 GB per day together) and surface TCWV and SP
(monthly files, about 1.2 GB each; SP masks the 850 hPa fields below the ground). About 1.7 TB per year, about 18.7 TB for 2007-2017 with the margin months.

## Steps

1. **Load the tools and check that your NERSC account is linked to Globus** (on a login node):

   ```bash
   module load globus-tools
   globus get-identities <your_nersc_username>@nersc.gov
   ```

   A UUID means the account is linked. `NO_SUCH_IDENTITY` means it is not: link it first (see the NERSC Globus page). The module loads a Python module, so do not
   combine it with `conda init` in the same shell.

2. **Generate the lists and scripts** for the first (test) year. This copies nothing; it checks that all source files exist, skips files that are already complete on
   scratch, checks your quota, and writes `list_*` files and `globus_copy_<year>.sh` into the current folder (or `$WORKDIR`):

   ```bash
   cd /global/homes/f/feng045/program/scream/mcs_environment/era5_copy
   bash make_era5_globus_script.sh 2007 2007
   ```

   The script of the first year also copies the December before (2006-12) and the script of the last year the January after (here 2008-01, the last hours of 2007).

3. **Renew the login tokens of the helper** (first use, and whenever a call fails with `AuthAPIError ... 400 Bad Request`). `transfer_files.py` keeps its own tokens in
   `~/.globus/transfer.json` and `~/.globus/<collection>.<collection>.json`. They are separate from the login of the `globus` command in step 1, so a working `globus get-identities` does
   not prove that they work, and tokens left over from earlier years are rejected by Globus with exactly that error. Run:

   ```bash
   generate_token.py -s dtn -t dtn --renew
   ```

   It deletes the old tokens and asks you to log in: it prints a URL, you open it in a browser, log in with Globus and paste the code back. It can ask twice (once for the transfer
   service, once for access to the NERSC DTN collection). The new tokens are stored in `~/.globus` and the following calls do not ask again. (The `--renew` option of `transfer_files.py`
   itself does nothing in the current module version; use `generate_token.py`.)

4. **Run the transfers.** The script stops at the first call that fails, so that a login problem shows up once and not for every month. After fixing the cause, run it again: a failed
   first call has submitted nothing; if a later call failed, look at `check_transfers.py` first and do not resubmit months that are already running.

   ```bash
   bash globus_copy_2007.sh
   ```

   Every call in the script is one Globus task (one month and type: 24 tasks for a year, 26 for the first and for the last year of a range, 28 when it is both). Globus allows 3 active and 100 pending tasks per user; a year script submits 24 to 28 tasks that finish about as fast as they are submitted (see step 8 for several years).

5. **Follow the tasks** (they run in the Globus service, you can log out). `check_transfers.py` lists the **oldest** tasks of your history first (without options the 10 oldest, not the
   newest), so ask for more and read the end of the list:

   ```bash
   check_transfers.py -n 200 -p | tail -30      # "task id | status" of your 30 newest tasks (the newest are at the bottom)
   check_transfers.py -n 200 | tail -60         # with the label (<user>_<date>_<time>), request time, completion time and status
   ```

   (`-d` adds the events of each task, `-i <task id>` selects one task.) The Globus web app (app.globus.org, Activity) shows the same tasks. The 28 tasks of the 2007 copy took 7 to 22 s each
   and the whole year 2.5 minutes (1.97 TB, about 14 GB/s, no faults).

6. **Verify** when all tasks of the year have succeeded (counts and byte sizes against CFS):

   ```bash
   bash verify_era5_copy.sh 2007 2007
   ```

   If it reports missing files or other sizes, run `make_era5_globus_script.sh 2007 2007` again (it lists only what is missing) and run the new `globus_copy_2007.sh`.

7. **Quota.** The files count toward your `/pscratch` quota (`lfs quota -h -u $USER /pscratch`; 100 TiB quota with 49.5 TiB used on 2026-11-20, so the full 18.7 TB, about 17 TiB, fits; about 12.5 k files
   of your 10 M file limit). The generator stops when the planned amount does not fit.

8. **Next years.** Once the test year is verified, the other years can be submitted back to back:

   ```bash
   bash make_era5_globus_script.sh 2008 2017      # a few minutes: lists what is missing (2007-12 is complete and skipped), checks the quota
   for y in $(seq 2008 2017); do bash globus_copy_$y.sh || break; done      # one year after the other, stops at the first failed call
   bash verify_era5_copy.sh 2008 2017
   ```

   Submitting the 240 tasks takes about 20 minutes (a few seconds per call). Run the loop inside `tmux` (or as `nohup bash -c 'for y in ...; do ...; done' > submit.log 2>&1 &`) so that a
   dropped connection does not stop the submissions halfway; the tasks that were already submitted keep running in any case.

   Globus keeps at most 3 active and 100 pending tasks per user, and the tasks finish about as fast as they are submitted (at most 4 of the 28 tasks of 2007 were in flight at the same time),
   so the queue stays short; the remaining 17 TB should take roughly 20 to 30 minutes. If a submission is ever refused because too many tasks are pending, the script stops: wait until
   `check_transfers.py -n 200 -p | tail -30` shows no ACTIVE task, run `make_era5_globus_script.sh` again (it lists only what is missing) and start the year scripts again.

The extraction reads the copy through `config/sources.yaml` (source `OBS`, roots below `/pscratch/sd/w/wcmca1/ERA5`).

## Troubleshooting

* **`globus_sdk.services.auth.errors.AuthAPIError: ('POST', 'https://auth.globus.org/v2/oauth2/token', None, 400, 'Error', 'Bad Request')`** raised in `activate_token` /
  `RefreshTokenAuthorizer`: the token that the helper stored in `~/.globus` is no longer accepted (expired or revoked; seen with files dated 2024). Do step 3
  (`generate_token.py -s dtn -t dtn --renew`), then run the script again. The files of `~/.globus` are credentials: do not copy or print them.
* **`check_transfers.py` shows only old tasks (for example the copies of September) and none of the new ones**: it lists the oldest tasks first and only 10 of them by default. Use
  `check_transfers.py -n 200 -p | tail -30` (step 5); the new tasks are at the end.
* **"Endpoint requires manual activation, please open the following URL"**: open the URL, activate the collection in the browser, and press ENTER in the terminal.
* **`Error transfering files:` followed by a message from Globus**: the message says what is wrong (for example a folder you may not write to); fix it and run the script again.
