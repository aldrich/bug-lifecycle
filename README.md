# Bug Lifecycle Scripts

Gather stats about bugs for further analysis

### Requirements

- Python 3
- virtualenv

### Setup

You will need to do this once, during setup.

- `virtualenv venv`
- `. venv/bin/activate`
- `pip3 install --editable .`

Edit the values found within config.ini, particularly your Conduit API token, which you can find in Settings. Also, in the `[PHIDs]` section add the PHIDs of the projects you want to track, otherwise they won't be usable in the query.

In subsequent calls, it is sufficient to just go to the directory of the script and do the following:

- `. venv/bin/activate` whenever entering the directory
- `lifecycle` (with arguments, if desired)

Please also check the options available from `lifecycle --help`. This is an example:

```
venv ❯ lifecycle -c 6 -y 2020 -p capacitor,messaging
```

This pulls all tickets _created_ in 2020 Cycle 6 (November-December) and that have the tags #capacitor AND #messaging.

The output should go to a CSV file that looks like the following:

```
id,phid,status,priority,created,closed,qa_verified,tagged_capacitor,tagged_client_success,tagged_data_science_infrastructure,tagged_design,tagged_freelancer_groups,tagged_freightlancer_x_local_jobs,tagged_messaging,tagged_qa_verified
T235313,PHID-TASK-jzzfv3favkg2nepovli7,Resolved,100,1615565541,1615777558,0,0,0,0,0,0,0,0,0
T234601,PHID-TASK-mm7nfmyi3zupjr6pm7fc,Open,100,1614911477,0,0,0,0,0,0,0,0,0,0
T235398,PHID-TASK-xk4e4ephgpjgirg2fdsj,Open,90,1615775295,0,0,0,0,0,0,0,0,0,0
T235393,PHID-TASK-xngr5ch3nwbkbwqdcs4h,Open,90,1615773431,0,0,0,0,0,0,0,0,0,0
```
