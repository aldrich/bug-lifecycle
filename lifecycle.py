import click
import configparser
import json
import re
import time
from phabricator import Phabricator

# Globals
phidMatcher = re.compile(r'PHID-BUGC-([a-zA-Z-_]+)')

ProjectPHIDMap = {}
QAVerifiedProjectPHID = ''


# Constants
CsvOutputPath = ''
TitleMaxLen = 30
FetchBatchSize = 50  # tickets fetched per batch (NOT the total tickets to fetch)
AllowedCycles = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']
MinimumYear = 2020
MaximumYear = 2021


def getTickets(phab, cycle, year, projectsStr):

    dateRange = getDateRange(cycle, year)
    dateStart = dateRange[0]
    dateEnd = dateRange[1]

    projectSlugs = getSlugs(projectsStr)
    projectPHIDs = [ProjectPHIDMap[slug] for slug in projectSlugs]

    constraints = {}

    if not projectSlugs:
        click.echo(
            f'Please specify at least one project from the list: {list(ProjectPHIDMap.keys())}')
        return

    if projectPHIDs:
        constraints['projects'] = projectPHIDs

    # note: dateStart and dateEnd referring to tickets CREATED within this period
    if dateStart:
        constraints['createdStart'] = dateStart
    if dateEnd:
        constraints['createdEnd'] = dateEnd

    click.echo(f'Valid project slugs in query: {projectSlugs}.')
    click.echo(f'Constraints to maniphest.search: {json.dumps(constraints)}')

    tickets = {}

    # Fetch ticket info through `maniphest.search`:
    # https://phabricator.tools.flnltd.com/conduit/method/maniphest.search/

    after = None
    page = 1
    click.echo(f'Fetching tickets from project:')
    while True:
        click.echo('.' * page)
        page = page + 1
        result = phab.maniphest.search(
            constraints=constraints,
            # attachments=attachments,
            limit=FetchBatchSize, after=after)
        after = result['cursor']['after']

        # dump(result.response)

        for ticket in result['data']:
            tickets[str(ticket['id'])] = {
                'id': ticket['id'],
                'phid': ticket['phid'],
                'title': ticket['fields']['name'],
                'status': ticket['fields']['status']['name'],
                'priority': ticket['fields']['priority']['value'],
                'dateCreated': ticket['fields']['dateCreated'],
                'dateClosed': ticket['fields']['dateClosed'] or 0,
            }

        if after == None:
            break

    allKeys = list(tickets.keys())
    # click.echo(f'{len(tickets)} tickets fetched: {", ".join(allKeys)}')

    idNumbers = [int(id) for id in list(tickets.keys())]
    timestamps = getTransactions(phab, projectSlugs, idNumbers)

    if len(timestamps) > 0:
        mergeTicketDicts(tickets, timestamps)
        fields = ticketFieldsBase() + ticketFields(projectSlugs) + ticketFieldsCustom()
        csvs = generateCSVs(tickets, fields)
        writeCSVsToFile(csvs, fields)
    else:
        click.echo('No data found! Try a different query.')


def fieldValuesTuple(ticket, fields):
    fieldValues = []
    for fieldname in fields:
        if fieldname in ['phid', 'status', 'title']:
            fieldValues.append(ticket.get(fieldname, '-'))
        else:
            fieldValues.append(ticket.get(fieldname, 0))
    return tuple(fieldValues)


def generateCSVs(tickets, fields):
    csvs = []
    formatElements = []

    for fieldname in fields:
        if fieldname in ['phid', 'status', 'title']:
            formatElements.append('%s')
        else:
            formatElements.append('%d')

    # formatStr could be smt like '%d;%s;%s;%d;%d;%d;%d;%d;%d'
    formatStr = ';'.join(formatElements)

    # print the header on to the console
    click.echo('---')
    click.echo(';'.join(fields))

    for _, ticket in tickets.items():
        # title = ticket['title'][:titleMaxLen]  # .ljust(titleMaxLen, ' ')
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
    ]

def ticketFields(projects):
    return [f'tagged_{value}' for value in projects]
    pass

def ticketFieldsCustom():
    return [
        # 'browser_chrome',
        # 'browser_firefox',
        # 'browser_ie',
        # 'browser_others',
        # 'browser_safari',
        # 'bug_reporter_automated_tests',
        # 'bug_reporter_internal_staff',
        # 'bug_reporter_qa',
        # 'bug_reporter_users',
        # 'environment_all',
        # 'environment_development',
        # 'environment_production',
        # 'environment_sandbox',
        # 'environment_staging',
        # 'platform_android',
        # 'platform_desktop_app',
        # 'platform_ios',
        # 'platform_linux',
        # 'platform_mac',
        # 'platform_others',
        # 'platform_windows',
        # 'root_cause_api_usage',
        # 'root_cause_backend_business_logic',
        # 'root_cause_backend_type_issue',
        # 'root_cause_business_logic',
        # 'root_cause_database_sql_queries',
        # 'root_cause_design_specification',
        # 'root_cause_frontend',
        # 'root_cause_frontend_configuration',
        # 'root_cause_infrastructure_configuration',
        # 'root_cause_infrastructure_failure',
        # 'root_cause_operational_error',
        # 'root_cause_product_specification',
        # 'root_cause_test_script_issue',
        # 'root_cause_third_party_dependency_failure',
        # 'root_cause_third_party_integration',
        # 'type_of_bug_bad_ux',
        # 'type_of_bug_browser_compatibility',
        # 'type_of_bug_error_handling',
        # 'type_of_bug_functionality',
        # 'type_of_bug_localization',
        # 'type_of_bug_performance',
        # 'type_of_bug_ui',
    ]


def writeCSVsToFile(csvs, fields):
    header = ';'.join(fields)
    # header = 'id;phid;status;priority;created;closed;tagged;platform_linux;platform_mac'

    with open(CsvOutputPath, 'w') as csvFile:
        click.echo("Dumping CSV data...")
        csvFile.write(f'{header}\n')
        csvFile.writelines(csvs)
        click.echo(f'Ticket data written out to {CsvOutputPath}.')


def mergeTicketDicts(intoDict, fromDict):
    keys = intoDict.keys()
    for key, value in intoDict.items():
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
    click.echo(f'Fetching transaction data from {count} tickets...')
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
                        # slug = ProjectPHIDMap[projectPHID]
                        timestamps[id][f'tagged_{projectSlug}'] = timestamp

    return timestamps


def isCreateTxn(txn):
    return txn['transactionType'] == 'core:create'


# time ticket changed from non-closed to closed
def isClosedTxn(txn):
    return txn['transactionType'] == 'status' and \
        isStatusOpen(txn['newValue']) == False and \
        isStatusOpen(txn['oldValue']) == True


# def isTagged(txn, projectPHID):
#     return txn['transactionType'] == 'core:edge' and \
#         not projectPHID in txn['oldValue'] and \
#         projectPHID in txn['newValue']

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
    return status == "open"


def dump(dict, useJson=True):
    if useJson:
        click.echo(json.dumps(dict))
    else:
        click.echo(dict)


def getProjects(phab, slug):
    # https://phabricator.tools.flnltd.com/conduit/method/project.search/
    constraints = {
        "slugs": [slug],
        "isRoot": True
    }
    result = phab.project.search(constraints=constraints)

    click.echo('Project found:')

    for project in result['data']:
        name = project['fields']['name']
        id = project['id']
        phid = project['phid']
        click.echo('» Project: %s (id=%s, phid=%s)' % (name, id, phid))


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
    # now determine the correct start and end time epoch units based on this.
    monthOpen = 1
    monthClose = 2  # we'll subtract one second from this to generate the last possible date for the cycle
    if cycle == 'C2':
        monthOpen = 3
        monthClose = 4
    elif cycle == 'C3':
        monthOpen = 5
        monthClose = 6
    elif cycle == 'C4':
        monthOpen = 7
        monthClose = 8
    elif cycle == 'C5':
        monthOpen = 9
        monthClose = 10
    elif cycle == 'C6':
        monthOpen = 11
        monthClose = 12

    dateOpen = int(time.mktime((year, monthOpen, 1, 0, 0, 0, 0, 0, 0)))
    dateClose = int(time.mktime(
        (year, monthOpen + 2, 1, 0, 0, 0, 0, 0, 0)) - 1)

    # click.echo(f'dateRange: {dateOpen} ... {dateClose}')
    return (dateOpen, dateClose)


def getSlugs(string):
    trimmed = [s.strip() for s in string.split(',')]
    return [s for s in trimmed if s in ProjectPHIDMap.keys()]


def loadConfig(isDev):

    global ProjectPHIDMap
    global QAVerifiedProjectPHID
    global FetchBatchSize
    global CsvOutputPath

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

    FetchBatchSize = config['Params']['fetch_batch_size']
    CsvOutputPath = config['Params']['csv_output_path']

    phabAPIToken = config[phabricatorConfigKey]['api_token']
    phabHost = config[phabricatorConfigKey]['host']

    click.echo('Configuration loaded.')
    return Phabricator(host=phabHost, token=phabAPIToken)

@click.command()
@click.option('--cycle', '-c', prompt='Cycle', type=click.Choice(AllowedCycles, case_sensitive=False), \
    help='Period in which the tickets were created')
@click.option('--year', '-y', prompt='Year', type=click.IntRange(MinimumYear, MaximumYear), \
    help='The year in which the tickets were created')
@click.option('--projects', '-p', prompt='Project tags (comma-separated)', \
    help='Comma-separated list of project tags (e.g. "messaging,client_success")')
@click.option('--dev', is_flag=True)
def cli(cycle, year, projects, dev):
    phab = loadConfig(dev)
    getTickets(phab, cycle, year, projects)

if __name__ == '__main__':
    cli()
