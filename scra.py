import json
import os.path
import re
import time
import traceback
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# custom exception
class DataAccessDenied(Exception):
  pass

def disable_wait():
  driver.implicitly_wait(0)

def enable_wait():
  driver.implicitly_wait(10) # 10 seconds

def element_exists(selector, context, return_el, wait):
  if not wait:
    disable_wait()

  try:
    el = context.find_element_by_css_selector(selector)
  except:
    el = None

  if not wait:
    enable_wait()

  return el if return_el else bool(el)

def child_element_count(el):
  return driver.execute_script("return arguments[0].childElementCount;", el)

def to_place_page(place_detail):
  driver.get(place_detail['url'])

def store_reviews(out, start_el):
  # if we dont have start_el, all reviews are considered
  if start_el is None:
    start_el = driver.find_element_by_css_selector('div[data-review-id="0"]')
    reviews = [start_el]
  else:
    reviews = []

  reviews = reviews + driver.execute_script('''
    var start_el = arguments[0],
      arr = [];
      node = start_el.nextElementSibling;

      while (node) {
        arr.push(node);
        node = node.nextElementSibling;
      }

      return arr;''', start_el)

  last_stored_el = reviews[-1]

  for review in reviews:
    try:
      review_obj = {}

      # expand the review
      more = element_exists('button[jsaction="pane.review.expandReview"]', review, True, False)
      if more and more.is_displayed():
        more.click()

      # find review text
      text_el = review.find_element_by_class_name('section-review-text')
      review_obj['text'] = text_el.text

      # stars
      stars = review.find_elements_by_class_name('section-review-star-active')
      review_obj['stars'] = len(stars)

      # publish date
      publish_date = review.find_element_by_class_name('section-review-publish-date')
      review_obj["publish_date"] = publish_date.text

      # local guide or not
      local_guide = review.find_element_by_class_name('section-review-subtitle-local-guide')
      if local_guide and local_guide.is_displayed():
        review_obj['local_guide'] = True 
      else:
        review_obj['local_guide'] = False

      # number of reviews done by the user
      other_reviews = review.find_element_by_css_selector('.section-review-subtitle:last-child')
      if other_reviews and other_reviews.is_displayed():
        matches = re.search('[.\d]+', other_reviews.text)
        review_obj['other_reviews'] = int(matches.group(0).replace('.', '')) if matches else 0
      else:
        review_obj['other_reviews'] = 0

      # find review thumbs
      review_thumbs_up = element_exists('.section-review-thumbs-up-count', review, True, False)
      if review_thumbs_up and review_thumbs_up.text:
        review_obj['thumbs_up'] = int(review_thumbs_up.text)
      else:
        review_obj['thumbs_up'] = 0

      out["reviews"].append(review_obj)
    except StaleElementReferenceException: 
      print("Stale element exception for {0}".format(out["name"]))
      continue

  return last_stored_el

def get_reviews(out):
  # get scroll and data box
  scrollbox = driver.find_element_by_class_name("section-scrollbox")
  databox = driver.find_element_by_css_selector("div.section-listbox:not(.section-listbox-root):not(.section-scrollbox)")
  loadedreviews = child_element_count(databox)
  store_state = None
  repeat = True

  # hardcoded wait to avoid stale elements
  time.sleep(1)

  if loadedreviews == 0:
    # ops... google doesnt want us to fetch reviews
    raise DataAccessDenied("Reviews not loading >:(")
  elif loadedreviews == out['review_count']:
    # saves all reviews
    store_state = store_reviews(out, store_state)

  while repeat and loadedreviews < out['review_count']:
    try:
      # scrolls down to load new reviews...
      driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollbox)
      # ...wait for new review to load
      if element_exists('div[data-review-id="{0}"]'.format(loadedreviews), databox, False, True):
        loadedreviews = child_element_count(databox)
        # save reviews
        store_state = store_reviews(out, store_state)
      else:
        break
    except:
      # that helpful error message thou
      print("Something happened while fetching review {0} for {1}".format(loadedreviews, out['name']))
      repeat = False

def save_result(data):
  with open('result.json', 'w') as out:
    json.dump(data, out)

def main():
  global driver

  path_to_chromedriver = '/home/arthurlorenzi/scrap/chromedriver'
  driver = webdriver.Chrome(executable_path = path_to_chromedriver)

  place_details = {}
  data = {} # scrap data
  resume_index = '' # we will scrap from this index to the end

  # loads place details file
  if os.path.isfile('place_detail.json'):
    with open('place_detail.json') as json_string:
      place_details = json.load(json_string)
  else:
    print("File place_detail.json not found")
    exit()

  # check previous result file
  if os.path.isfile('result.json'):
    with open('result.json') as json_string:
      data = json.load(json_string)
      if 'interruption_index' in data:
        # continue from where we stopped
        resume_index = data.pop('interruption_index', None)

  # start scrapping
  enable_wait()

  for key in sorted(place_details.keys()):
    try:
      # not very pretty
      if key < resume_index or key == 'fails':
        continue

      data[key] = record_out = {
        "error": '',
        "closed": 'permanently_closed' in place_details[key],
        "name": place_details[key]['name'],
        "review_count": 0,
        "reviews": []
      }

      if record_out['closed'] or not 'reviews' in place_details[key]:
        continue;

      # navigate to place page
      to_place_page(place_details[key])

      # go to reviews
      try:
        open_reviews = WebDriverWait(driver, 10).until(
          EC.visibility_of_element_located((By.CSS_SELECTOR, 'button[jsaction="pane.rating.moreReviews"]'))
        )
        digit_list = re.findall('\d+', open_reviews.text)
        record_out['review_count'] = int(''.join(digit_list))
        open_reviews.click()
      except:
        print("review button was not found for {0} :(".format(record_out['name']))
        continue

      try:
        # stores review data on output object "record_out"
        get_reviews(record_out)
      except DataAccessDenied as err:
        print("Data access denied exception for {0}".format(record_out['name']))
        data["interruption_index"] = key
        break

      # save what we have so far
      save_result(data)

    except Exception as err:
      # in case of a unexpected exception
      traceback.print_exc()
      data["interruption_index"] = key
      break

  save_result(data)
  driver.close()

if __name__ == "__main__":
  main()
