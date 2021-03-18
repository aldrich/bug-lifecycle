import click
import configparser
import json
import re
import time
from datetime import datetime
from phabricator import Phabricator

# Globals
phidMatcher = re.compile(r'PHID-BUGC-([a-zA-Z-_]+)')
cycleMatcher = re.compile(r'^(\d{4})c([1-6]$)', re.IGNORECASE)

ProjectPHIDMap = {}
QAVerifiedProjectPHID = ''
CustomFieldsEnabled = []

# Constants
# Note: these are overwritten when calling `loadConfig`
# tickets fetched per API call (NOT the total tickets to fetch)
FetchBatchSize = 50
MinimumYear = 2020
MaximumYear = 2021
CsvOutputPath = ''


def getTickets(phab, dateStart, dateEnd, projectsStr, onlyBugs, trackAllProjects):

    projectSlugs = getSlugs(projectsStr) if projectsStr else ''
    projectPHIDs = [ProjectPHIDMap[slug] for slug in projectSlugs]

    constraints = {}

    shouldConstraintSubtypes = onlyBugs
    if not projectSlugs:
        validTags = ', '.join(list(ProjectPHIDMap.keys()))
        click.echo(
            f'No valid project tags were recognized. Please include at least one of the following: {validTags}')
        shouldConstraintSubtypes = True
    else:
        # projects is an ALL-sesarch. Only results which match all projectPHIDs are returned
        constraints['projects'] = projectPHIDs
        # we can decide later if subtypes can optionally be applied to this case as well

    if shouldConstraintSubtypes:
        click.echo('Restricting ticket search to "Bug" subtypes.')
        constraints['subtypes'] = ['bugcategorization', 'bugcat']

    # note: dateStart and dateEnd referring to tickets CREATED within this period
    if dateStart:
        constraints['createdStart'] = dateStart
    if dateEnd:
        constraints['createdEnd'] = dateEnd

    click.echo(f'Valid project slugs in query: {projectSlugs}.')
    click.echo(f'Constraints to maniphest.search: {json.dumps(constraints)}')

    tickets = {}

    # add all the other slugs not named (if desired)
    if trackAllProjects:
        click.echo('Tracking timestamps for all listed projects')
        projectSlugs = list(ProjectPHIDMap.keys())

    # Fetch ticket info through `maniphest.search`:
    # https://phabricator.tools.flnltd.com/conduit/method/maniphest.search/

    timestampNow = int(datetime.timestamp(datetime.now()))
    after = None
    page = 1
    click.echo(f'Pulling Maniphest tickets...')
    while True:
        click.echo('.' * page)
        page = page + 1
        result = phab.maniphest.search(
            constraints=constraints,
            # attachments=attachments,
            limit=FetchBatchSize, after=after)
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
                'status': ticket['fields']['status']['name'],
                'priority': ticket['fields']['priority']['value'],
                'dateCreated': dateCreated,
                'dateClosed': dateClosed,
                'days_open_to_close': daysToClose,  # from open
                'timestamp': timestampNow,
            }

        if after == None:
            break

    idNumbers = [int(id) for id in list(tickets.keys())]
    itemName = 'bugs' if onlyBugs else 'tickets'
    click.echo(f'{len(idNumbers)} {itemName} found')

    chunkedIdNumbers = list(chunks(idNumbers, FetchBatchSize))
    fields = ticketFieldsBase() + ticketFields(projectSlugs) + ticketFieldsCustom()

    for idChunk in chunkedIdNumbers:
        click.echo('.' * page)
        page = page + 1
        timestamps = getTransactions(phab, projectSlugs, idChunk)
        if len(timestamps) > 0:
            mergeTicketDicts(tickets, timestamps)
        else:
            click.echo('No data found! Try a different query.')

    for key, tick in tickets.items():
        dateClosed = tick['dateClosed'] or 0
        if 'qa_verified' in tick.keys():
            dateQAVerified = tick['qa_verified']
            tick['qa_verified_to_close'] = - \
                1 if dateClosed == 0 else int(
                    (dateClosed - dateQAVerified) / 86400)
        else:
            tick['qa_verified_to_close'] = -1
    csvs = generateCSVs(tickets, fields)
    writeCSVsToFile(csvs, fields)


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


def generateCSVs(tickets, fields):
    csvs = []
    formatElements = []

    for fieldname in fields:
        if fieldname in ['phid', 'status', 'title', 'id']:
            formatElements.append('%s')
        else:
            formatElements.append('%d')

    # formatStr could be smt like '%d,%s,%s,%d,%d,%d,%d,%d,%d'
    formatStr = ','.join(formatElements)

    # print the header on to the console
    click.echo('---')
    click.echo(','.join(fields))

    for _, ticket in tickets.items():
        line = f'{formatStr}' % fieldValuesTuple(ticket, fields)
        click.echo(line)
        line += '\n'
        csvs.append(line)

    click.echo('---')
    return csvs


def ticketFieldsBase():
    # all fields have type int, unless explicitly noted
    return [
        'id',
        'phid',  # string
        'status',  # string
        'priority',
        'created',
        'closed',
        'qa_verified',
        'days_open_to_close',
        'qa_verified_to_close',
        'timestamp'
    ]


def ticketFields(projects):
    return [f'tagged_{value}' for value in projects]


def ticketFieldsCustom():
    return CustomFieldsEnabled


def writeCSVsToFile(csvs, fields):
    header = ','.join(fields)
    with open(CsvOutputPath, 'w') as csvFile:
        click.echo("Dumping CSV data...")
        csvFile.write(f'{header}\n')
        csvFile.writelines(csvs)
        click.echo(f'Ticket data written out to {CsvOutputPath}.')


def mergeTicketDicts(intoDict, fromDict):
    for key, _ in fromDict.items():
        intoDict[key].update(fromDict[key])
    return intoDict


def getTransactions(phab, projectSlugs, ids=[]):
    # ids should be of list<int> type
    count = len(ids)
    if count < 1:
        click.echo('No tickets found.')
        return []

    # Note: maniphest.gettasktransactions is a deprecated method in
    # Conduit. But we lack other options to get a list of transactions for
    # multiple tickets in a single call.
    click.echo(f'Pulling transaction data from {count} tickets...')
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
                        timestamps[id][f'tagged_{projectSlug}'] = timestamp

    return timestamps


def isCreateTxn(txn):
    return txn['transactionType'] == 'core:create'


# time ticket is set to some closed state
def isClosedTxn(txn):
    return txn['transactionType'] == 'status' and \
        isStatusClosed(txn['newValue'])


def isTagged(txn, slug):
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
    if isinstance(value, list):
        return value
    elif isinstance(value, str):
        # value can be an array. we initially expected a string.
        valuesInListStr = phidMatcher.findall(value)
        return valuesInListStr
    else:
        return [value]  # probably would fail


def getDateRange(cycle, year):
    # now determine the correct start and end time epoch units based on cycle
    # and year.
    startMonth = cycle * 2 - 1
    dateOpen = int(time.mktime((year, startMonth, 1, 0, 0, 0, 0, 0, 0)))
    dateClose = int(time.mktime(
        (year, startMonth + 2, 1, 0, 0, 0, 0, 0, 0)) - 1)
    return (dateOpen, dateClose)


def getSlugs(string):
    trimmed = [s.strip() for s in string.split(',')]
    return [s for s in trimmed if s in ProjectPHIDMap.keys()]


def loadConfig(isDev):

    global ProjectPHIDMap
    global QAVerifiedProjectPHID
    global FetchBatchSize
    global CsvOutputPath
    global CustomFieldsEnabled

    click.echo('Loading config...')

    if isDev:
        click.echo('Development mode on')

    config = configparser.ConfigParser()
    config.read('config.ini')

    # a if a is not None else b
    phidsConfigKey = 'PHIDs_Dev' if isDev else 'PHIDs'
    phabricatorConfigKey = 'Phabricator_Dev' if isDev else 'Phabricator'

    projectMap = {}
    for key in config[phidsConfigKey]:
        projectMap[key] = config[phidsConfigKey][key]

    ProjectPHIDMap = projectMap
    QAVerifiedProjectPHID = config[phabricatorConfigKey]['qa_verified_project_phid']
    ProjectPHIDMap['qa_verified'] = QAVerifiedProjectPHID

    FetchBatchSize = int(config['Params']['fetch_batch_size'])
    CsvOutputPath = config['Params']['csv_output_path']

    phabAPIToken = config[phabricatorConfigKey]['api_token']
    phabHost = config[phabricatorConfigKey]['host']

    customFieldsSection = config['Custom_Fields']
    CustomFieldsEnabled = []
    for key in customFieldsSection.keys():
        if customFieldsSection[key] == '1':
            CustomFieldsEnabled.append(key)

    click.echo('Configuration loaded.')
    return Phabricator(host=phabHost, token=phabAPIToken)


@click.command()
@click.option('--created-in-cycle', '-cc', type=click.STRING,
              help='The year and cycle in which the tickets were created the format is YYYYCX, \
where YYYY is the year and X is a number between 1 and 6. For example: "2021C1". If used, neither \
of --start-date or --end-date should be used.')
@click.option('--start-date', type=click.INT,
              help='Earliest timestamp for tickets in \
query. If used, must also include --end-date, and --created-in-cycle should be omitted.')
@click.option('--end-date', type=click.INT,
              help='Latest timestamp for tickets in \
query. If used, must also include --start-date, and --created-in-cycle should be omitted.')
@click.option('--projects', '-p',
              prompt='Project tags (comma-separated)',
              help='Comma-separated list of project tags (e.g. "messaging,client_success"). \
Note: All VALID tags found will be used in the ticket search.')
@click.option('--track-all-projects',
              is_flag=True,
              help='If enabled, will record timestamps in which a ticket is tagged with a \
project, for each project listed in the [PHIDs] section in config.ini (this includes projects \
not named in --projects). Note that `qa_verified` is always tracked.')
@click.option('--only-bugs',
              is_flag=True,
              help='If set, only return tickets with the Bug \
subtype. This option is automatically set when no recognized projects were specified.')
@click.option('--dev',
              is_flag=True,
              help='Run on a local Phabricator instance (specify \
    params on config.ini)')
def cli(created_in_cycle, start_date, end_date, projects, track_all_projects, only_bugs, dev):
    """This is a commandline tool to load Maniphest tickets created
within a time period (year and cycle), and collects timestamps for
each, including for open and closed date, and the dates when a given
project / tag had been first assigned to the ticket.
    """
    phab = loadConfig(dev)

    # check params
    if created_in_cycle != None and (start_date != None or end_date != None):
        click.echo(
            'Please include only one of --created-in-cycle, or --start-date/--end-date ')
        return

    if created_in_cycle != None:

        dateRange = getDateRangeFromCycleStr(created_in_cycle)
        if dateRange != None:
            click.echo(dateRange)
        else:
            click.echo('no date range found!')
            return

        (dateStart, dateEnd) = dateRange

    else:
        # should have both start_date and end_date
        if start_date == None or end_date == None:
            click.echo('Please specify both --start-date and --end-date')
            return
        if start_date > end_date:
            click.echo('Make sure start date <= end date')
            return

        dateStart = start_date
        dateEnd = end_date

    getTickets(phab, dateStart, dateEnd, projects,
               only_bugs, track_all_projects)


def getDateRangeFromCycleStr(cycleStr):
    # convert year and cycle to start and end create epochs
    matches = cycleMatcher.findall(cycleStr)
    if len(matches) != 1 or len(matches[0]) != 2:
        click.echo('invalid input to cycle. Format should be "YYYYCX"')
        return None

    (year, cycle) = (int(matches[0][0]), int(matches[0][1]))

    if year < 2019 or year > 2029:
        click.echo('Invalid year (2019-2029)')
        return None

    if cycle < 1 or cycle > 6:
        click.echo('Invalid cycle (1-6)')
        return None

    # click.echo(f'Year: {year} Cycle: C{cycle}')
    return(getDateRange(cycle, year))


if __name__ == '__main__':
    cli()
