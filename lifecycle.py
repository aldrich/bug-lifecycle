import click
import configparser
import json
import re
import sys
import time
from datetime import datetime
from phabricator import Phabricator

# Globals
phidMatcher = re.compile(r'PHID-BUGC-([a-zA-Z-_]+)')
cycleMatcher = re.compile(r'^(\d{4})c([1-6]$)', re.IGNORECASE)

# Note: these are overwritten when calling `loadConfig`
ProjectPHIDMap = {}
CustomFieldsEnabled = []
QuietMode = False
FetchBatchSize = 50


def getTicketData(phab, dateStart, dateEnd, validProjectSlugs, onlyBugs):
    """
    Returns tickets (and the timestamps of key lifecycle events) as a dictionary
    keyed by the ticket id
    """
    constraints = {}

    shouldConstrainToBugSubtypes = onlyBugs

    if shouldConstrainToBugSubtypes:
        log('Restricting ticket search to "Bug" subtypes.')
        constraints['subtypes'] = ['bugcategorization', 'bugcat']

    # note: dateStart and dateEnd referring to tickets CREATED within this period
    if dateStart:
        constraints['createdStart'] = dateStart
    if dateEnd:
        constraints['createdEnd'] = dateEnd

    tickets = {}

    for slug in validProjectSlugs:
        projectPHID = ProjectPHIDMap[slug]
        # log(f'Fetching tickets for {slug} (PHID: {projectPHID})')
        ticks = getTicketForProject(phab=phab,
                                    projectPHID=projectPHID,
                                    constraints=constraints)

        log(f'{len(ticks)} ticket(s) found for {slug}')
        tickets.update(ticks)

    # log(f'{len(tickets)} found for {len(validProjectSlugs)} projects')

    idNumbers = [int(id) for id in list(tickets.keys())]

    chunkedIdNumbers = list(chunks(idNumbers, FetchBatchSize))

    for idChunk in chunkedIdNumbers:
        timestamps = getTransactions(phab, validProjectSlugs, idChunk)
        if len(timestamps) > 0:
            mergeTicketDicts(tickets, timestamps)
        else:
            log('No data found! Try a different query.', isError=True)

    for _, tick in tickets.items():
        dateClosed = tick['dateClosed'] or 0
        if 'qa_verified' in tick.keys():
            dateQAVerified = tick['qa_verified']
            tick['qa_verified_to_closed'] = - \
                1 if dateClosed == 0 else int(
                    (dateClosed - dateQAVerified) / 86400)
        else:
            tick['qa_verified_to_closed'] = -1

    return tickets


def getTicketForProject(phab, projectPHID, constraints):
    """
    Fetch ticket info through `maniphest.search`:
    https://phabricator.tools.flnltd.com/conduit/method/maniphest.search/

    Return as a dictionary of ticket metadata keyed by the ticket ID.
    """
    timestampNow = int(datetime.timestamp(datetime.now()))
    tickets = {}
    constraints['projects'] = [projectPHID]
    # log(f'Constraints to maniphest.search: {json.dumps(constraints)}')

    after = None
    # iteratively fetch a batch of 50(?) tickets based on the
    # constraints given.
    while True:
        result = phab.maniphest.search(constraints=constraints,
                                       limit=FetchBatchSize,
                                       after=after)
        after = result['cursor']['after']

        for ticket in result['data']:
            strTicket = str(ticket['id'])
            dateCreated = ticket['fields']['dateCreated']
            dateClosed = ticket['fields']['dateClosed'] or 0
            daysToClose = -1 if dateClosed == 0 else int(
                (dateClosed - dateCreated) / 86400)

            tickets[strTicket] = {
                'id': ticket['id'],
                'phid': ticket['phid'],
                'title': ticket['fields']['name'],
                'status': ticket['fields']['status']['name'].upper(),
                'priority': ticket['fields']['priority']['value'],
                'dateCreated': dateCreated,
                'dateClosed': dateClosed,
                'days_open_to_closed': daysToClose,  # from open
                'timestamp': timestampNow,
            }

        if after == None:
            break

    return tickets


def chunks(lst, n):
    """Yield successive n-sized chunks from lst."""
    for i in range(0, len(lst), n):
        yield lst[i:i + n]


def fieldValuesTuple(ticket, fields):
    fieldValues = []
    for fieldname in fields:
        if fieldname in ['phid', 'status', 'title', 'id']:
            value = ticket.get(fieldname, '-')
            if fieldname == 'id':
                value = 'T' + str(value)
            fieldValues.append(value)
        else:
            fieldValues.append(ticket.get(fieldname, 0))
    return tuple(fieldValues)


def printTicketDataCSV(tickets, fields):
    """
    Output the tickets (dictionary) in CSV format. Fields
    supplied are used as basis of determining extra columns
    generated.
    """
    # print the header on to the console
    log(','.join(fields), ignoreQuiet=True)

    formatElements = []
    for fieldname in fields:
        if fieldname in ['phid', 'status', 'title', 'id']:
            formatElements.append('%s')
        else:
            formatElements.append('%d')

    # formatStr could be smt like '%d,%s,%s,%d,%d,%d,%d,%d,%d'
    formatStr = ','.join(formatElements)

    for _, ticket in tickets.items():
        line = f'{formatStr}' % fieldValuesTuple(ticket, fields)
        log(line, ignoreQuiet=True)


def ticketFieldsBase():
    # all fields have type int, unless explicitly noted
    return [
        'id',
        'status', # is string
        'priority',
        'created',
        'closed',
        'qa_verified',
        'days_open_to_closed',
        'qa_verified_to_closed',
        'timestamp'
    ]


def ticketFields(projects):
    return [f't_{value}' for value in projects]


def ticketFieldsCustom():
    return CustomFieldsEnabled


def mergeTicketDicts(intoDict, fromDict):
    for key, _ in fromDict.items():
        intoDict[key].update(fromDict[key])
    return intoDict


def getTransactions(phab, projectSlugs, ids=[]):
    """
    Returns transaction data for specified tickets (through a list of ids
    passed), as well as when a ticket is first tagged by one of the projects
    whose slugs are given.
    """

    # ids should be of list<int> type
    count = len(ids)
    if count < 1:
        log('No tickets found', isError=True)
        return []

    # Note: maniphest.gettasktransactions is a deprecated method in
    # Conduit. But we lack other options to get a list of transactions for
    # multiple tickets in a single call.
    log(f'Get transaction data from {count} tickets')
    transactionsDict = phab.maniphest.gettasktransactions(ids=ids).response

    ids = list(transactionsDict.keys())
    timestamps = {}

    for id in ids:
        timestamps[id] = {}

        # transactions for a ticket are sorted descending timestamp
        transactions = list(transactionsDict[id])

        # record the first time a field is changed to a value we
        # are watching.
        for txn in transactions:
            # this goes through the list of a tickets transactions in
            # chronological order, starting from the earliest.
            timestamp = int(txn['dateCreated'])
            oldValues = listFromTransactionValue(txn['oldValue'])
            newValues = listFromTransactionValue(txn['newValue'])

            if isCreateTxn(txn):
                timestamps[id]['created'] = timestamp
            elif isClosedTxn(txn):
                timestamps[id]['closed'] = timestamp
            elif isCustomFieldChangeTransaction(txn):
                # we want to be able to generate a series of these tests given a list of fields
                for customFieldName in ticketFieldsCustom():
                    if isValueAddedInList(customFieldName, newValues, oldValues):
                        timestamps[id][customFieldName] = timestamp
            else:
                if isTagged(txn, 'qa_verified'):
                    timestamps[id][f'qa_verified'] = timestamp
                for projectSlug in projectSlugs:
                    if isTagged(txn, projectSlug):
                        timestamps[id][f't_{projectSlug}'] = timestamp

    return timestamps


def isCreateTxn(txn):
    return txn['transactionType'] == 'core:create'


def isClosedTxn(txn):
    """
    Returns the timestamp when ticket is set to some closed
    state (NOTE: for the very first time)
    """
    return txn['transactionType'] == 'status' and \
        isStatusClosed(txn['newValue'])


def isTagged(txn, slug):
    """
    Returns whether a transaction is referring to an
    event in which the given project slug is assigned
    to the affected ticket (NOTE: for the very first time)
    """
    projectPHID = ProjectPHIDMap[slug]
    return txn['transactionType'] == 'core:edge' and \
        not projectPHID in txn['oldValue'] and \
        projectPHID in txn['newValue']


def isCustomFieldChangeTransaction(txn):
    return txn['transactionType'] == 'core:customfield'


def isValueAddedInList(value, newList, oldList):
    return value in newList and not value in oldList


def isStatusOpen(status):
    return status.lower() == "open"


def isStatusClosed(status):
    return status.lower() in ['duplicate', 'invalid', 'resolved', 'wontfix']


def listFromTransactionValue(value):
    """
    Returns a list (of PHIDs) from a ticket transaction object.
    """
    if isinstance(value, list):
        return value
    elif isinstance(value, str):
        # value can be an array. we initially expected a string.
        return phidMatcher.findall(value)
    else:
        return [value] # probably would fail


def getDateRange(cycle, year):
    """
    Computes for the correct start and end time epoch units based on cycle
    and year.
    """
    startMonth = cycle * 2 - 1
    dateOpen = int(time.mktime((year, startMonth, 1, 0, 0, 0, 0, 0, 0)))
    dateClose = int(time.mktime(
        (year, startMonth + 2, 1, 0, 0, 0, 0, 0, 0)) - 1)
    log(f'Date range: {dateOpen}...{dateClose}')
    return (dateOpen, dateClose)


def log(obj, isError=False, ignoreQuiet=False):
    if isError == True:
        print(obj, file=sys.stderr)
        return
    if QuietMode == False or ignoreQuiet == True:
        click.echo(obj)


def loadConfig(isQuiet):
    """
    Load the config.ini values, some into global variables. It also returns
    the phabricator object that you use to access the Conduit methods.
    """
    configFileName = 'config.ini'

    global ProjectPHIDMap
    global FetchBatchSize
    global CustomFieldsEnabled
    global QuietMode

    # should happen here because you might need to log strings here.
    QuietMode = isQuiet

    config = configparser.ConfigParser()
    config.read(configFileName)

    ProjectPHIDMap['qa_verified'] = config['Phabricator']['qa_verified_project_phid']
    FetchBatchSize = int(config['Phabricator']['fetch_batch_size'])
    phabAPIToken = config['Phabricator']['api_token']
    phabHost = config['Phabricator']['host']

    customFieldsSection = config['Custom_Fields']
    CustomFieldsEnabled = []
    for key in customFieldsSection.keys():
        if customFieldsSection[key] == '1':
            CustomFieldsEnabled.append(key)

    return Phabricator(host=phabHost, token=phabAPIToken)

def getProjectSlugs(string):
    """
    Using values from ProjectPHIDMap, return a list of only the valid slug names
    from a string containing a comma-separated list inputted by the user.
    """
    trimmed = [s.strip() for s in string.split(',')]
    ret = []
    badSlugs = []
    for s in trimmed:
        if s in ProjectPHIDMap.keys():
            ret.append(s)
        else:
            badSlugs.append(s)

    if len(badSlugs) > 0:
        log(
            f'You have mispelled some project tags: {", ".join(badSlugs)}', isError=True)
    return ret

def fetchPHIDMapFromProjectsString(phab, projectSlugsStr):
    """
    Use a Phabricator Conduit method to search for PHID values
    from project 'slugs' inputted and get all valid PHIDs into
    a map that is returned.
    """
    slugs = [s.strip() for s in projectSlugsStr.split(',')]
    projectSlugs = slugs if projectSlugsStr else ''
    constraints = {'slugs': projectSlugs}
    slugsDict = phab.project.search(
        constraints=constraints
        ).response['maps']['slugMap']
    slugMap = {}
    for slug in slugsDict:
        slugMap[slug] = slugsDict[slug]['projectPHID']
    return slugMap


def checkDateParams(createdInCycle, startDate, endDate):
    """
    Checks the params given to the command-line interface.
    The rule is this: use only one of createdInCycle or the pair
    of startDate and endDate. If neither is supplied,
    createdInCycle will be prompted.

    Returns a 2-tuple of UNIX timestamps for start and end, but if
    input is invalid, a null value.
    """

    if createdInCycle != None and (startDate != None or endDate != None):
        log(
            'Please include only one of --cycle, or --start-date/--end-date', isError=True)
        return None

    if createdInCycle != None:
        dateRange = getDateRangeFromCycleStr(createdInCycle)
        if dateRange == None:
            log('No date range found!', isError=True)
            return None
        return dateRange

    else:
        # should have both start_date and end_date
        if startDate == None or endDate == None:
            # prompt for cycle / year
            s = click.prompt('Year and Cycle (e.g. 2020C1)', type=click.STRING)
            dateRange = getDateRangeFromCycleStr(s)
            if dateRange == None:
                log('No date range found!', isError=True)
                return None
            return dateRange

        if startDate > endDate:
            log('Make sure that start date comes before end date', isError=True)
            return None
        return (startDate, endDate)


def getDateRangeFromCycleStr(cycleStr):
    """
    Convert year and cycle to start and end create epochs, returning
    a 2-tuple of UNIX epoch timestamps. For now, some restrictions apply
    and the earliest value you can give is 2019C1.
    """

    matches = cycleMatcher.findall(cycleStr)
    if len(matches) != 1 or len(matches[0]) != 2:
        log('Invalid input to cycle. Format should be "YYYYCX"', isError=True)
        return None

    (year, cycle) = (int(matches[0][0]), int(matches[0][1]))

    if year < 2019 or year > 2029:
        log('Invalid year (2019-2029)', isError=True)
        return None

    if cycle < 1 or cycle > 6:
        log('Invalid cycle (1-6)', isError=True)
        return None

    return(getDateRange(cycle, year))


@click.command()
@click.option('--cycle', '-c', type=click.STRING,
              help='The year and cycle in which the tickets were created. The value should \
be a string that looks like "2021C1". If this option is used, neither of --start-date or \
--end-date must also be used.')
@click.option('--start-date', '-s', type=click.INT,
              help='Earliest creation date (UNIX epoch timestamp) for tickets in \
query. If used, must also include --end-date, and --created-in-cycle should be omitted.')
@click.option('--end-date', '-e', type=click.INT,
              help='Latest creation date (UNIX epoch timestamp) for tickets in \
query. If used, must also include --start-date, and --created-in-cycle should be omitted.')
@click.option('--projects', '-p',
              prompt='Project tags (comma-separated)',
              help='Comma-separated list of project tags (e.g. "messaging,client_success"). \
For best results, avoid inputting a long list of projects.')
@click.option('--only-bugs', '-b',
              is_flag=True,
              help='If set, only return tickets with the "Bug Categorization" subtype.')
@click.option('--quiet', '-q',
              is_flag=True,
              help='Suppress stdout generation unrelated to the final output')
def cli(cycle, start_date, end_date, projects, only_bugs, quiet):
    """This is a commandline tool to load Maniphest tickets created
within a time period (e.g. year and cycle), and outputs timestamps for
each, including for open and closed date, as well as the dates when a
given project / tag is first assigned to the ticket.
    """

    phab = loadConfig(quiet)

    projects = projects.lower()

    slugMap = fetchPHIDMapFromProjectsString(phab, projects)
    ProjectPHIDMap.update(slugMap)

    dateRange = checkDateParams(cycle, start_date, end_date)
    if dateRange == None:
        return
    (dateStart, dateEnd) = dateRange

    validProjectSlugs = getProjectSlugs(projects) if projects else ''

    fields = ticketFieldsBase() + ticketFields(validProjectSlugs) + ticketFieldsCustom()

    # This is the output for the ticket data requested that we should be adding to
    # Dashboard
    tickets = getTicketData(phab, dateStart, dateEnd, validProjectSlugs, only_bugs)

    printTicketDataCSV(tickets, fields)


if __name__ == '__main__':
    cli()


"""
TODO:
- improve documentation
- add a JSON output option
- add `--only-closed` option
- sort by some specified category
"""
