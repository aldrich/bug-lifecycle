# Bug Lifecycle Scripts

Gather stats about bugs for further analysis

### Requirements

- Python 3
- virtualenv

### Setup

You will need to do this once, during setup.

- Edit the script `phabAPIToken` and use your own Conduit token, which you can find in settings
- `virtualenv venv`
- `. venv/bin/activate`
- `pip3 install --editable`

Afterwards it is sufficient to just go to the directory of the script and do the following:

- `. venv/bin/activate`
- `lifecycle`

Please also check the options available from `lifecycle --help`.
