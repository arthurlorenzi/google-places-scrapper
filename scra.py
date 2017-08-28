import json, os.path, re, shutil, time, traceback
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# custom exception
class ReviewsNotLoading(Exception):
  pass

class tail_review_changed(object):
  def __init__(self, context, old_tail):
    self.context = context
    self.old_tail = old_tail

  def __call__(self, driver):
    tail = driver.execute_script("return arguments[0].lastChild;", self.context)
    if tail != self.old_tail:
      return tail
    else:
      return False

def backup_data():
  if not os.path.isfile('place_details.orig.json'):
    shutil.copy2('place_details.json', 'place_details.orig.json')

def load():
  if os.path.isfile('place_details.json'):
    with open('place_details.json') as json_string:
      return json.load(json_string)
  else:
    return None

def log_interruption(output, key, e):
  output["interruption"] = {
    "key": key,
    "str": str(e),
    "repr": repr(e)
  }

def save_result(data):
  with open('place_details.json', 'w') as out:
    json.dump(data, out)

def safe_find(context, selector):
  try:
    el = context.find_element_by_css_selector(selector)
  except:
    el = None

  return el

def go_to_reviews(place):
  open_reviews = driver.find_element_by_css_selector('button[jsaction="pane.rating.moreReviews"]')
  place['review_count'] = int(''.join(re.findall('\d+', open_reviews.text)))
  open_reviews.click()

def scrap_popular_times(place):
  popular_times = driver.find_elements_by_css_selector('.section-popular-times-container > div')
  # search for popular times
  if popular_times and len(popular_times) == 7:
    place['popular_times'] = {}
    day_number = 0;

    for day in popular_times:
      place['popular_times'][day_number] = {}
      hour_number = 6;

      hours = day.find_elements_by_css_selector('.section-popular-times-bar')

      if len(hours) == 1: # place isnt open that day
        continue

      for hour in hours:
        bar = hour.find_element_by_css_selector('.section-popular-times-value')
        if not bar:
          bar = hour.find_element_by_css_selector('.section-popular-times-current-value')

        place['popular_times'][day_number][hour_number] = int(bar.get_attribute("aria-label")[:-1])
        hour_number += 1

      day_number += 1


def scrap_reviews(place, msg_prefix):
  # remove API reviews
  place['reviews'] = []

  # wait until scrollbox loads
  scrollbox = wait.until(
    EC.presence_of_element_located((By.CLASS_NAME, 'section-scrollbox'))
  )
  databox = driver.find_element_by_css_selector("div.section-listbox:not(.section-listbox-root):not(.section-scrollbox)")

  # hardcoded await to avoid stale elements
  time.sleep(1)

  loaded_reviews = driver.execute_script("return arguments[0].childElementCount;", databox)
  head_review = driver.execute_script("return arguments[0].firstChild", databox)

  if loaded_reviews == 0:
    # ops... google doesnt want us to fetch reviews
    raise ReviewsNotLoading("Reviews not loading >:(")
  
  # saves first review
  place['reviews'].append(scrap_review(head_review))
  last_scraped_review = head_review
  tail_review = None
  scrap_count = 1

  if loaded_reviews == place['review_count']:
    # saves all reviews
    scrap_new_reviews(place, head_review)
    return

  while scrap_count < place['review_count']:
    # scrolls down to load new reviews...
    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollbox)
    # ...wait for new reviews
    tail_review = wait.until(tail_review_changed(databox, tail_review))
    # scrap reviews
    scrap_count += scrap_new_reviews(place, last_scraped_review)
    head_review = remove_reviews(head_review, tail_review)
    last_scraped_review = tail_review
    print("\r{0} - {1} - Reviews scraped: {2}/{3}".format(
      msg_prefix, place['name'], scrap_count, place['review_count']), end = ""
    )
  print("")

def scrap_new_reviews(place, last_scraped_review):
  reviews = driver.execute_script('''
    var node = arguments[0].nextElementSibling,
        arr = [];

      while (node) {
        arr.push(node);
        node = node.nextElementSibling;
      }

      return arr;''', last_scraped_review)

  for review in reviews:
    place["reviews"].append(scrap_review(review))

  return len(reviews)

def remove_reviews(head_review, tail_review):
  # always preserve 20 reviews
  remove_count = (int(tail_review.get_attribute("data-review-id"))
    - int(head_review.get_attribute("data-review-id")) - 20)

  return driver.execute_script('''
    var node = arguments[0],
      count = Number(arguments[1]),
      aux;

    for (var i = 0; i < count; ++i) {
      aux = node;
      node = node.nextElementSibling;
      aux.remove();
    }

    return node;
    ''', head_review, remove_count)

def scrap_review(review):
  review_obj = {}

  # expand the review
  more = safe_find(review, 'button[jsaction="pane.review.expandReview"]')
  if more and more.is_displayed():
    more.click()

  # find review author
  author_el = review.find_element_by_css_selector('.section-review-title > span')
  review_obj['author_name'] = author_el.text

  # find review text
  text_el = review.find_element_by_class_name('section-review-text')
  # store only the original comment
  matches = re.search('^\(Translated by Google\).*\n*\(Original\)\n*(.*)', text_el.text)
  if matches:
    review_obj['text'] = match.group(1)
    review_obj['lang'] = None
  else:
    review_obj['text'] = text_el.text
    review_obj['lang'] = 'en'

  # stars
  stars = review.find_elements_by_class_name('section-review-star-active')
  review_obj['rating'] = len(stars)

  # publish date
  publish_date = review.find_element_by_class_name('section-review-publish-date')
  review_obj["relative_time_description"] = publish_date.text

  # local guide or not
  local_guide = review.find_element_by_class_name('section-review-subtitle-local-guide')
  if local_guide.is_displayed():
    review_obj['local_guide'] = True 
  else:
    review_obj['local_guide'] = False

  # number of reviews done by the user
  other_reviews = review.find_element_by_css_selector('.section-review-subtitle:last-child')
  if other_reviews.is_displayed():
    matches = re.search('[.\d]+', other_reviews.text)
    review_obj['other_reviews'] = int(matches.group(0).replace('.', '')) if matches else 0
  else:
    review_obj['other_reviews'] = 0

  # find review thumbs
  review_thumbs_up = safe_find(review, '.section-review-thumbs-up-count')
  if review_thumbs_up and review_thumbs_up.text:
    review_obj['thumbs_up'] = int(review_thumbs_up.text)
  else:
    review_obj['thumbs_up'] = 0

  review_obj['scrap_time'] = time.time();

  return review_obj

def main():

  backup_data()

  place_details = load()
  
  if place_details is None:
    print("File place_details.json not found")
    return
  else:
    resume_index = '' # we will scrap from this index
    if 'interruption' in place_details:
      resume_index = place_details["interruption"]["key"]
      place_details.pop("interruption", None)

  global driver
  driver = webdriver.Chrome(executable_path='/home/arthurlorenzi/scrap/chromedriver')

  global wait
  wait = WebDriverWait(driver, 20)

  i = 0
  for key in sorted(place_details.keys()):
    try:
      i += 1
      place = place_details[key]

      # not very pretty
      if (key < resume_index or key == 'fails'
          or 'permanently_closed' in place):
        continue

      # en, es-419, pt-BR
      driver.get(place['url'] + '&hl=en')

      time.sleep(1)

      scrap_popular_times(place)

      if not 'reviews' in place:
        place['review_count'] = 0
        continue
      
      #driver.save_screenshot('out.png');

      go_to_reviews(place)

      scrap_reviews(place, "Place {0}/{1}".format(i, len(place_details.keys())))

      # save what we have so far
      save_result(place_details)

    except TimeoutException:
      # failed to load reviews
      place["scrap_interruption"] = { "type": "timeout" }
      print("")
      continue
    except StaleElementReferenceException:
      # this is bad too
      place["scrap_interruption"] = { "type": "stale_element_reference" }
      print("")
      continue
    except ReviewsNotLoading as e:
      log_interruption(place_details, key, e)
      break
    except Exception as e:
      # in case of a unexpected exception
      log_interruption(place_details, key, e)
      break

  save_result(place_details)
  driver.close()

if __name__ == "__main__":
  main()
