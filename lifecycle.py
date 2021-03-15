import click
import json
import re
import time
from phabricator import Phabricator

# Prod
phabAPIToken = "api-xxxxxxxxxxxxxxxxxxxxxxxxxxxx"
phabHost = "https://phabricator.tools.flnltd.com/api/"
projectPHIDsTracked = ['PHID-PROJ-2iilroan6csa7qrk4rph']  # Capacitor

# My local
# phabAPIToken = "api-tnjkevfufq4qcgxvwa3wzpnt3mke"
# phabHost = "http://phabricator.local:8081/api/"
# projectPHIDsTracked = ['PHID-PROJ-r5j6oaiz4mwg2tjmx2pg']
#    'PHID-PROJ-zp3j4coyacc543jafokw']  # de Grails, Caioni's

phab = Phabricator(host=phabHost, token=phabAPIToken)

# for timestamps use https://www.epochconverter.com/
csvOutputPath = '/Users/aldrichco/Desktop/output.csv'
titleMaxLen = 30
limit = 50  # tickets fetched per batch (NOT the total tickets to fetch)

allowedCycles = ['C1', 'C2', 'C3', 'C4', 'C5', 'C6']
minimumYear = 2020
maximumYear = 2021

phidMatcher = re.compile(r'PHID-BUGC-([a-zA-Z-_]+)')

# tags=[QAVerified, Capacitor]
# date_range (like cycle / year)
# status=open
# min_priority=normal (or low, wishlist, high, unbreak now)


def getTickets(dateStart, dateEnd):
    # https://phabricator.tools.flnltd.com/conduit/method/maniphest.search/
    constraints = {}

    if projectPHIDsTracked:
        constraints['projects'] = projectPHIDsTracked

    # note: dateStart and dateEnd referring to tickets CREATED within this period
    if dateStart:
        constraints['createdStart'] = dateStart
    if dateEnd:
        constraints['createdEnd'] = dateEnd

    click.echo(constraints)
    # adding attachments could significantly add to the query time!
    # attachments = {
    #     'projects': 1 # access by result['data']['attachments']['projects']['projectPHIDs']
    # }

    tickets = {}

    # get tickets through maniphest.search
    after = None
    page = 1
    while True:
        click.echo(f'Fetching tickets from project, part {page}...')
        page = page + 1
        result = phab.maniphest.search(
            constraints=constraints,
            # attachments=attachments,
            limit=limit, after=after)
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
    timestamps = getTransactions(idNumbers)

    if len(timestamps) > 0:
        mergeTicketDicts(tickets, timestamps)
        fields = ticketFieldsBase() + ticketFieldsCustom()
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

    click.echo(';'.join(fields))

    for fieldname in fields:
        if fieldname in ['phid', 'status', 'title']:
            formatElements.append('%s')
        else:
            formatElements.append('%d')

    # formatStr could be smt like '%d;%s;%s;%d;%d;%d;%d;%d;%d'
    formatStr = ';'.join(formatElements)

    for _, ticket in tickets.items():
        # title = ticket['title'][:titleMaxLen]  # .ljust(titleMaxLen, ' ')
        line = f'{formatStr}\n' % fieldValuesTuple(ticket, fields)
        csvs.append(line)
        click.echo(line)
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
    ] + [f'tagged_{PHID}' for PHID in projectPHIDsTracked]


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

    with open(csvOutputPath, 'w') as csvFile:
        click.echo("Dumping CSV data...")
        csvFile.write(f'{header}\n')
        csvFile.writelines(csvs)
        click.echo(f'Ticket data written out to {csvOutputPath}.')


def mergeTicketDicts(intoDict, fromDict):
    keys = intoDict.keys()
    for key, value in intoDict.items():
        intoDict[key].update(fromDict[key])
    return intoDict


def getTransactions(ids=[]):
    # ids should be of list<int> type
    count = len(ids)
    if count < 1:
        click.echo('No tickets found.')
        return []

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
                for projectPHID in projectPHIDsTracked:
                    if isTagged(txn, projectPHID):
                        timestamps[id][f'tagged_{projectPHID}'] = timestamp
    return timestamps


def isCreateTxn(txn):
    return txn['transactionType'] == 'core:create'


# time ticket changed from non-closed to closed
def isClosedTxn(txn):
    return txn['transactionType'] == 'status' and \
        isStatusOpen(txn['newValue']) == False and \
        isStatusOpen(txn['oldValue']) == True


def isTagged(txn, projectPHID):
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


def getProjects(slug):
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


@click.command()
@click.option('--cycle', '-c', prompt='Cycle', type=click.Choice(allowedCycles, case_sensitive=False))
@click.option('--year', '-y', prompt='Year', type=click.IntRange(minimumYear, maximumYear))
def cli(cycle, year):
    # getProjects('capacitor_app')
    dateRange = getDateRange(cycle, year)

    getTickets(dateRange[0], dateRange[1])


if __name__ == '__main__':
    cli()
