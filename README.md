# Bug Lifecycle Scripts

A Python script that gather stats about Maniphest bug tickets for further analysis

### Requirements

- [virtualenv](https://virtualenv.pypa.io/en/latest/)

### Setup

You will need to do this once, during setup. In the script folder, do the following

- `virtualenv venv`
- `. venv/bin/activate`
- `pip install -e .`

Edit the values found within config.ini, particularly your Conduit API Token, which you can find in the [Settings](https://phabricator.tools.flnltd.com/settings) page.

In subsequent calls, it is sufficient to just go to the directory of the script and do the following:

- `. venv/bin/activate` whenever entering the directory
- `lifecycle`

Please also check the options available from `lifecycle --help`. This is an example:

```
venv ❯ lifecycle -c 2021c2 -p capacitor_app,messaging -f csv -b
```

This pulls all tickets _created_ in 2021 Cycle 2 (March-April), with the project tags #capacitor_app AND #messaging. The output format is CSV (JSON is also supported), and only bugs (read: those with 'Bug' ticket subtype) are returned.

The output should go to `stdout` that looks like the following:

```
id,status,priority,created,closed,qa_verified,days_open_to_closed,qa_verified_to_closed,timestamp,t_capacitor_app,t_messaging
T234536,OPEN,LOW,1614841620,0,1614841620,-1,-1,1616417873,1614841620,0
T234519,OPEN,LOW,1614831037,0,1614831037,-1,-1,1616417873,1614831037,0
T234344,RESOLVED,LOW,1614674387,1616400179,1614674387,19,19,1616417873,1614674387,0
T234343,OPEN,LOW,1614674028,0,1614674028,-1,-1,1616417873,1614674028,0
T234234,OPEN,LOW,1614589203,0,1614589203,-1,-1,1616417873,1614589203,0
T234214,OPEN,LOW,1614577576,0,1614577576,-1,-1,1616417874,1614577576,1614577576
T234348,OPEN,NEEDS TRIAGE,1614680241,0,0,-1,-1,1616417874,0,1614681806
T234242,OPEN,LOW,1614599260,0,0,-1,-1,1616417874,0,1614599260
T234473,OPEN,WISHLIST,1614792928,0,0,-1,-1,1616417874,0,1614866664
```

An explanation of some of the columns:

- `id` - the Maniphest ticket ID.
- `status` - one of OPEN, RESOLVED, WONTFIX, INVALID, DUPLICATE
- `priority` - ticket priority
- `created` - timestamp from when the ticket was created
- `closed` - timestamp from when the ticket was first closed.
- `qa_verified` - timestamp from when the ticket was first tagged 'QA Verified'
- `days_open_to_closed` - number of days between ticket is opened and when it is closed (-1 if still open)
- `qa_verified_to_closed` - number of days between ticket is tagged 'QA Verified' and when it is closed (-1 if still open, or when not tagged)
- `timestamp` - timestamp from when the API returned the results for this ticket
- `t_capacitor_app`, `t_messaging`, ...etc - indicates the timestamp from when a ticket is tagged with one of the projects given in the params
