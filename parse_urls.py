import requests
from fake_useragent import UserAgent
from bs4 import BeautifulSoup
import re
import time
import sys
import json
import logging
import smtplib
import os
try:
    from configparser import ConfigParser
except ImportError:
    from ConfigParser import ConfigParser
from pymongo import MongoClient
import argparse

# Read in the configuration file details
inifile = "config.ini"  # Location of ini file
config = ConfigParser(allow_no_value=True)
config.sections()

# Read ini file (used to get logging info)
try:
    config.read(inifile)
except EnvironmentError:
    print('def process(). Issue Reading Config File')
    configinfo.close()
    sys.exit(1)

# Set-up the Logging criteria:
logfile_location = str(config.get('general', 'log_file'))

FORMAT = '%(asctime)-15s  %(module)s:%(lineno)d %(levelname)s %(message)s'
logging.basicConfig(filename=logfile_location, format=FORMAT,
                    level=logging.INFO)  # WARN ETC


# Parse the arguments
parser = argparse.ArgumentParser(description='Get Sites to Scan')
# Define Multiple arguments ('+' = 1 or more)
parser.add_argument('-nargs', nargs='+')

# Example usage based on above:
# python {0} -nargs site1 site2 site3 etc
for _, value in parser.parse_args()._get_kwargs():
    if value is not None:
        site_to_scan = value
    else:
        program = sys.argv[0]
        sys.stderr.write("Check arguments. Usage: %s -nargs <list of sites> \
            \n" % program)
        sys.exit(1)

# Set-up MongodB location.
if ('DB_PORT_27017_TCP_ADDR' in os.environ):
    host = os.environ['DB_PORT_27017_TCP_ADDR']
else:
    host = '192.168.99.100'

client = MongoClient(host, 27017)
db = client.finance

###############################################################
# Start of methods:
###############################################################
def check_db_for_urls(urls_to_follow, overall_content):
    urls_to_filter = []

    for url in urls_to_follow:
        found = db.finance.find_one({"url": url})

        if not found:
            overall_content = overall_content + "\nNew URL found. Adding following URL to db: " + url
            info_to_add = {"url": url, "datetime": time.strftime("%d-%m-%Y %H:%M")}
            urls_to_filter.append(url)
            resultdb = db.finance.insert_one(info_to_add)
        else:
            overall_content = overall_content + "\nURL Matchings one in db. Ignoring URL."
    return urls_to_filter


def search_base_url_for_links(seed_url):
    starttime = time.strftime("%H:%M:%S")
    base_url = str(config.get(seed_url, 'base_url'))
    base_tag = str(config.get(seed_url, 'base_tag'))
    base_attr = str(config.get(seed_url, 'base_attr'))
    base_attr_value = str(config.get(seed_url, 'base_attr_value'))
    # print base_url, base_tag, base_attr, base_attr_value
    user_agent = UserAgent()
    #Temporarily using:
    #file_name = '_url_finance.html'           # output file name
    #soup = BeautifulSoup(open(file_name, 'r'), 'lxml')
    #overall_content = ''

    page = requests.get(base_url, headers={'user-agent': user_agent.chrome})
    soup = BeautifulSoup(page.text, 'lxml')

    topnews = soup.find(base_tag, attrs={base_attr: base_attr_value})

    current_time = time.strftime("%d-%m-%Y %H:%M")
    overall_content = "Time/Date program run: " + str(current_time) + "\nPrinting Text from 'Top Global News' Section:\n=============================================================="

    text_all = topnews.find_all('div')
    for text in text_all:
        try:
            if text.string != None:
                overall_content = overall_content + '\n' + str(text.string)
            else:
                overall_content = overall_content + '\n' + re.sub('<[^>]+>', '', str(text))
        except Exception:
            overall_content = overall_content + "\n**Error reading Headline text. Skipping this Headline**"
            pass

    url_all = topnews.find_all('a')

    overall_content += "\n\nPrinting URLs for the 'Top Global News' Section:\n=============================================================="

    urls_to_follow = []
    for url in url_all:
        if re.match("http", url['href']):
            overall_content = overall_content + '\n' + url['href']
            urls_to_follow.append(url['href'])
        else:
            overall_content = overall_content + '\n' + base_url + url['href']
            urls_to_follow.append(base_url + url['href'])

    urls_to_filter = check_db_for_urls(urls_to_follow, overall_content)
    urls_to_sentiment = []
    for url in urls_to_filter:
        overall_content, sentiment_url = search_url_for_content(url, seed_url, overall_content)
        if sentiment_url:
            urls_to_sentiment.append(sentiment_url)
        time.sleep(5)  # Delay between requests

    overall_content = overall_content + "\n\n\nSUMMARY: URLS/Content that would be passed to Sentiment Analysis are:"
    overall_content = overall_content + "\n==============================================================="
    for url in urls_to_sentiment:
        overall_content = overall_content + '\n' + str(url)
    endtime = time.strftime("%H:%M:%S")
    overall_content += '\n\nProgram Duration: Start Time = ' + str(starttime) + ', End Time = ' + str(endtime)
    print overall_content
    email_content(overall_content)


def search_url_for_content(url, seed_url, overall_content):
    url_for_sentiment_analysis = ''
    user_agent = UserAgent()
    page = requests.get(url, headers={'user-agent': user_agent.chrome})
    soup = BeautifulSoup(page.text, 'lxml')

    story_tag = str(config.get(seed_url, 'story_tag'))
    story_attr = str(config.get(seed_url, 'story_attr'))
    story_attr_value = str(config.get(seed_url, 'story_attr_value'))

    story = soup.find('div', attrs={story_attr: story_attr_value})
    content = ''
    # Get content from highlighted text from heading 1 to 6 tags
    headings = ['h1', 'h2', 'h3', 'h4', 'h5', 'h6']
    for heading in headings:
        text = story.find_all(heading)  # Returns list
        if text:
            for elem in text:
                try:
                    content = content + '\n' + elem.string
                except Exception:
                    content = content + '\n' + "Heading exception found. Skipping this heading"
                    pass
    content = content + '\n'

    # Get main content of story
    for tag in story:
        if tag.name is 'p':
            if tag.string != None:
                content = content + '\n' + tag.string
            else:
                # Look to remove all < /> tags in text
                try:
                    content = content + '\n' + re.sub('<[^>]+>', '', str(tag))
                except Exception:
                    overall_content = overall_content + '\n' + "P Tag exception found. Skipping this line."
                    pass
    match, match_found = filter_content(content)

    if match:
        overall_content = overall_content + "\n=====================================================\nMATCH FOUND IN STORY (PRINTED BELOW) FOR FOLLOWING FILTER WORDS/PHRASES: " + match_found + "\n============================================"
        url_for_sentiment_analysis = url
    else:
        overall_content = overall_content + "\n=====================================================\nNO MATCH FOUND IN STORY (PRINTER BELOW) FOR FILTER WORDS/PHRASES\n============================================"
    overall_content = overall_content + "\n\nAdding Story Content for URL: " + url + "\n" + content
    return overall_content, url_for_sentiment_analysis


def filter_content(content):
    words_to_filter = json.loads(config.get('filter_content', 'words'))
    match_found = ''
    match = False
    for word in words_to_filter:
        if re.search(word, content):
            match_found = match_found + ' ' + word
            match = True
    return match, match_found


def email_content(content):
    # create an email message with just a subject line,
    current_time = time.strftime("%d-%m-%Y %H:%M")
    msg = 'Subject: ' + current_time + ': Results of latest scan...\n\n\n' + content
    # set the 'from' address,
    fromaddr = str(config.get('email', 'username'))  # 'YOUR_EMAIL_ADDRESS'
    password = str(config.get('email', 'password'))
    if not fromaddr:
        return
    if not password:
        return
    # set the 'to' addresses,
    toaddrs = json.loads(config.get('email', 'recipients'))

    # setup the email server,
    server = smtplib.SMTP('smtp.gmail.com', 587)
    server.starttls()

    # add my account login name and password,
    server.login(fromaddr, password)

    # send the email
    server.sendmail(fromaddr, toaddrs, msg)
    # disconnect from the server
    server.quit()


def main():
    # Starting 'seed' url is:
    for seed_url in site_to_scan:
        search_base_url_for_links(seed_url)

    # Close MongodB connection.
    client.close()


if __name__ == '__main__':
    main()
