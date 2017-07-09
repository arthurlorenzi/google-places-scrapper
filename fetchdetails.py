import json
import os.path
import pandas
import requests

# as the name suggests, this script fetch details of places

api_key = '' # your API key
path_to_csv = 'place_data.csv' # this file should contain place_ids of interest on index 'place_id'

if not api_key:
  print("Error: open fetchdetails.py and configure your API key at the top of the script... yeah... i know... it sucks")
  exit()

df = pandas.read_csv(path_to_csv)
url = 'https://maps.googleapis.com/maps/api/place/details/json?placeid={0}&key=' + api_key

data = {
  'fails': []
}
start = 0

# check whether we should resume some fetching done earlier
if os.path.isfile('place_detail.json'):
  with open('place_detail.json') as json_string:
    data = json.load(json_string)
    if 'interruption_index' in data:
      start = data.pop('interruption_index', None)

for i in range(start, len(df)):
  record = df.loc[i]
  place_id = record['place_id']

  r = requests.get(url.format(place_id))
  res = r.json();

  # well... lets continue later
  if res['status'] == 'OVER_QUERY_LIMIT':
    data['interruption_index'] = i
    break

  if r.status_code == 200 and res['status'] != 'NOT_FOUND':
    data[place_id] = res['result'];
  else:
    data['fails'].append({ 'place_id':place_id, 'index': i })

with open('place_detail.json', 'w') as out:
  json.dump(data, out)
