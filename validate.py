# validate.py - Unizin UCDM and UCW validator
#
# Copyright (C) 2018 University of Michigan Teaching and Learning

UNIZIN_FILE = "unizin_{table}.csv"

RESULTS_FILE = open("u_results.txt", "w")
ERRORS_FILE = open("u_errors.txt", "w")

## don't modify anything below this line (except for experimenting)

import sys, os, csv, itertools, argparse, smtplib

from email.mime.text import MIMEText

import psycopg2

import numpy as np
import pandas as pd

import dbqueries

from collections import OrderedDict
from operator import itemgetter

from tqdm import tqdm

from dotenv import load_dotenv
load_dotenv()

class SimpleQuoter(object):
    @staticmethod
    def sqlquote(x=None):
        return "'bar'"

def lower_first(iterator):
    return itertools.chain([next(iterator).lower()], iterator)

def load_CSV_to_dict(infile, indexname):
    df = pd.read_csv(infile, delimiter=',', dtype=str)
    # Lower case headers
    df.columns = map(str.lower, df.columns)
    df[indexname] = pd.to_numeric(df[indexname], errors='coerce', downcast='integer')

    df = df.fillna('NoData')
    return df.set_index(indexname, drop=False)

#def close_compare(a, b):
#    if (isinstance(a, float) and isinstance(b,float)):
#        return np.isclose(a,b)
#    return a == b

def close_compare(i, j):
    try:
        i = float(i)
        j = float(j)
        return np.isclose(i,j)
    except ValueError:
        return i==j

def compare_CSV(tablename):
    RESULTS_FILE.write(f"Comparing on {tablename}\n")
    sis_file = dbqueries.QUERIES[tablename]['sis_file'].format(date=os.getenv("SIS_DATE"))
    index = dbqueries.QUERIES[tablename]['index']
    try:    
        SIS_df = load_CSV_to_dict(sis_file.format(table=tablename), index)
        Unizin_df = load_CSV_to_dict(UNIZIN_FILE.format(table=tablename), index)
    except Exception as e:
        print ("Exception ",e)
        return

    SIS_len = len(SIS_df)
    Unizin_len = len(Unizin_df)

#    print (SIS_df)
#    print (Unizin_df)
    
    RESULTS_FILE.write ("Unizin rows: %d, SIS rows: %d\n" % (Unizin_len, SIS_len))

    if len(Unizin_df) == 0 or len(SIS_df) == 0:
        RESULTS_FILE.write(f"This table {tablename} has a empty record for at least one dataset, skipping\n")
        return

    lendiff = Unizin_len - SIS_len
    if lendiff > 0:
        RESULTS_FILE.write("Unizin has %d more rows than SIS for this table\n" % abs(lendiff))
    elif lendiff < 0:
        RESULTS_FILE.write("SIS has %d more rows than Unizin for this table\n" % abs(lendiff))

    Unizin_head = list(Unizin_df)
    print (Unizin_head)

    RESULTS_FILE.flush()
    for i, SIS_r in tqdm(SIS_df.iterrows(), total=SIS_len):
        #Look at all the unizin headers and compare
        indexval = SIS_r[index]
        if not indexval:
            continue
        try: 
            Unizin_r = Unizin_df.loc[indexval]
        except:
            #print (f"Index error on {indexval}")
            continue

#        f = np.frompyfunc(close_compare, 2, 1)

        for head in Unizin_head:
            try:
#               f(SIS_r[head], Unizin_r[head])
                if not close_compare(SIS_r[head], Unizin_r[head]):
#                    RESULTS_FILE.write("type SIS %s, type Unizin %s\n" % (type(SIS_r[head]),type(Unizin_r[head])))
                    RESULTS_FILE.write(f"{head} does not match for {indexval} SIS: {SIS_r[head]} Unizin: {Unizin_r[head]}\n")
            except Exception as e:
                ERRORS_FILE.write("%s\n" % str(e)) 
                continue

def load_Unizin_to_CSV(tablename):
    out_filename = UNIZIN_FILE.format(table=tablename)
    print (f"Loading ucdm {tablename} table to {out_filename}")
    # The DSN might switch depending on the data file
    conn = psycopg2.connect(os.getenv("DSN_"+dbqueries.QUERIES[tablename]['dsn']))
    
    curs = conn.cursor()

    query = dbqueries.QUERIES[tablename]
    if (query.get('prequery')):
        curs.execute(query.get('prequery'))
    UWriter = open(out_filename,"w")
    # Try this first with this, breaks in 8.0 though :()
    try:
        outputquery = "COPY ({0}) TO STDOUT WITH CSV HEADER FORCE QUOTE *".format(query.get('query'))
        curs.copy_expert(outputquery, UWriter)
    except psycopg2.ProgrammingError:
        print ("Copy query failed, trying regular query, possibly 8.0")
        writer = csv.writer(UWriter)

        conn.reset()
        curs.execute(query.get('query'))
        writer.writerows(curs.fetchall())

def email_results(filename, subject=None):
    with open(filename) as fp:
    # Create a text/plain message
        msg = MIMEText(fp.read())

    if (not subject):
        subject = f"CSV Validation for {filename}"
    msg['Subject'] = subject
    msg['From'] = os.getenv("SMTP_FROM")
    msg['To'] = os.getenv("SMTP_TO")

    print (f"Emailing out {filename}")
    server = smtplib.SMTP(os.getenv("SMTP_HOST"), os.getenv("SMTP_PORT"), None, 5)
    server.send_message(msg)
    server.quit()

#select_tables = ['academic_term']
select_tables = list(csv.reader([os.getenv("SELECT_TABLES", "academic_term")]))[0]

print (select_tables)

parser = argparse.ArgumentParser()
parser.add_argument("-o", "--option", type=int, help="Run an option by number",)
args = parser.parse_args()

option = args.option

if (not option):
    print ("""Choose an option.
    1 = Import *All* Unizin Data from GCloud to CSV (need developer VPN or other connection setup)
    2 = Import *select* table(s) from GCloud to CSV (need developer VPN or other connection setup)
    3 = Load/Compare *All* CSV files
    4 = Load/Compare *select* table(s)
    5 = Import/Compare for Canvas data loaded into Unizin 
    """)
    print ("'Select table(s)' are: ", ', '.join(select_tables))
    option = int(input())

print (f"Running option {option}")
if option == 1:
    for key in dbqueries.QUERIES.keys():
        load_Unizin_to_CSV(key)
elif option == 2:
    for key in dbqueries.QUERIES.keys():
        if key in select_tables:
            load_Unizin_to_CSV(key)
elif option == 3:
    for key in dbqueries.QUERIES.keys():
        compare_CSV(key)
elif option == 4:
    for key in dbqueries.QUERIES.keys():
        if key in select_tables:
            compare_CSV(key)
elif option == 5:
    # Only run this query
    key = "number_of_courses_by_term"
    load_Unizin_to_CSV(key)
    subject = dbqueries.QUERIES[key].get('query_name')
    email_results(UNIZIN_FILE.format(table=key), subject=subject)
else: 
    print(f"{option} is not currently a valid option")

sys.exit(0)
