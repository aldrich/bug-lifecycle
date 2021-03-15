# Bug Lifecycle Scripts

Gather stats about bugs for further analysis

### Requirements

- Python 3
- virtualenv

### Setup

You will need to do this once, during setup.

- `virtualenv venv`
- `. venv/bin/activate`
- `pip3 install --editable`

Edit the values found within config.ini, particularly your Conduit API token, which you can find in Settings. Also, in the `[PHIDs]` section add the PHIDs of the projects you want to track, otherwise they won't be usable in the query.

In subsequent calls, it is sufficient to just go to the directory of the script and do the following:

- `. venv/bin/activate` whenever entering the directory
- `lifecycle` (with arguments, if desired)

Please also check the options available from `lifecycle --help`. This is an example:

```
venv ❯ lifecycle -c 6 -y 2020 -p capacitor,messaging
```

This pulls all tickets *created* in 2020 Cycle 6 (November-December) and that have the tags #capacitor AND #messaging.
