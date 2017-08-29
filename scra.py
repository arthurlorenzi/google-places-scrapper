import json, os, re, time, traceback
from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# custom exception
class ReviewsNotLoading(Exception):
  pass

class last_child_changed(object):
  def __init__(self, context):
    self.context = context
    self.old_last = driver.execute_script("return arguments[0].lastChild;", self.context)

  def __call__(self, driver):
    last = driver.execute_script("return arguments[0].lastChild;", self.context)
    if last != self.old_last:
      # returns first element after old last child
      return driver.execute_script("return arguments[0].nextElementSibling", self.old_last)
    else:
      return False

conf = {
  # en, es-419, pt-BR,...
  "lang": "en",
  "translation_text": "(Translated by Google)",
  "same_lang_only": True,
  "comments_only": True
}

def load():
  with open("place_details.json", "r") as json_string:
    return json.load(json_string)

def interruption_index():
  try:
    with open(".interruption.info", "r") as json_string:
      index = json.load(json_string)["key"]
    os.remove('.interruption.info')
  except FileNotFoundError:
    index = ''

  return index

def log_interruption(output, key, e):
  with open(".interruption.info", "w") as out:
    json.dump({
      "key": key,
      "str": str(e),
      "repr": repr(e)
    }, out)

def save_progress(key, data):
  with open('scrap-result', 'a') as out:
    out.write(key + ":" + json.dumps(data) + "\n")

def safe_find(context, selector):
  try:
    el = context.find_element_by_css_selector(selector)
  except:
    el = None

  return el

def go_to_reviews():
  open_reviews = wait.until(
    EC.element_to_be_clickable((By.CSS_SELECTOR, 'button[jsaction="pane.rating.moreReviews"]'))
  )
  count = int(''.join(re.findall('\d+', open_reviews.text)))
  open_reviews.click()

  return count

def scrap_popular_times():
  data = {}
  popular_times = driver.find_elements_by_css_selector('.section-popular-times-container > div')
  # search for popular times
  if popular_times and len(popular_times) == 7:
    day_number = 0;

    for day in popular_times:
      data[day_number] = {}
      hour_number = 6;

      hours = day.find_elements_by_css_selector('.section-popular-times-bar')

      if len(hours) == 1: # place isnt open that day
        continue

      for hour in hours:
        bar = hour.find_element_by_css_selector('.section-popular-times-value')
        if not bar:
          bar = hour.find_element_by_css_selector('.section-popular-times-current-value')

        data[day_number][hour_number] = int(bar.get_attribute("aria-label")[:-1])
        hour_number += 1

      day_number += 1

  return data

def scrap_reviews(review_count, msg_prefix):
  data = []

  # wait until scrollbox loads
  scrollbox = wait.until(
    EC.presence_of_element_located((By.CLASS_NAME, 'section-scrollbox'))
  )
  databox = driver.find_element_by_css_selector("div.section-listbox:not(.section-listbox-root):not(.section-scrollbox)")

  # hardcoded await to avoid stale elements
  time.sleep(1)

  first_reviews_count = driver.execute_script("return arguments[0].childElementCount;", databox)
  if first_reviews_count == 0:
    # ops... google doesnt want us to fetch reviews
    raise ReviewsNotLoading("Reviews not loading >:(")
  
  head_review = driver.execute_script("return arguments[0].firstChild", databox)
  next_review = head_review
  loaded_reviews = 0
  stop = False

  while True:
    # scrap reviews
    reviews = get_new_reviews(next_review)

    loaded_reviews += len(reviews)

    for review in reviews:
      if ((conf['comments_only'] and not has_comment(review))
        or (conf['same_lang_only'] and not has_conf_lang(review))):
        # "Most helpful" criteria ranks first reviews that are written
        # in the same language that Maps is loaded, then reviews in other
        # languages and then reviews that doesn't have comments. So it is
        # safe to stop when a comment that doesn't match our criteria is
        # found
        stop = True
        break
      else:
        data.append(scrap_review(review))

    print("\r{0} - Reviews loaded: {1}/{2}"
      .format(msg_prefix, loaded_reviews, review_count), end = "")

    if loaded_reviews == review_count or stop:
      break

    # scrolls down to load new reviews...
    driver.execute_script("arguments[0].scrollTop = arguments[0].scrollHeight", scrollbox)
    # ...wait for new reviews...
    next_review = wait.until(last_child_changed(databox))
    # ...remove some elements if needed
    head_review = remove_reviews(head_review, next_review)

  print(" [Loaded comments based on criteria]")

  return data

def get_new_reviews(next_review):
  return [next_review] + driver.execute_script('''
    var node = arguments[0].nextElementSibling,
        arr = [];

      while (node) {
        arr.push(node);
        node = node.nextElementSibling;
      }

      return arr;''', next_review)

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

def has_comment(review):
  text_el = review.find_element_by_class_name('section-review-text')

  return True if text_el.text else False

def has_conf_lang(review):
  text_el = review.find_element_by_class_name('section-review-text')

  return False if conf['translation_text'] in text_el.text else True

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
  review_obj['text'] = text_el.text
  review_obj['lang'] = conf['lang'] if conf['same_lang_only'] else None

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
  place_details = load()
  resume_index = interruption_index() # we will scrap from this index

  global driver
  driver = webdriver.Chrome(executable_path='/home/arthurlorenzi/scrap/chromedriver')

  global wait
  wait = WebDriverWait(driver, 20)

  i = 0
  for key in sorted(place_details.keys()):
    try:
      i += 1
      place = place_details[key]
      scraped_data = {}

      # not very pretty
      if (key < resume_index or key == 'fails'
          or 'permanently_closed' in place):
        continue

      driver.get(place['url'] + '&hl=' + conf['lang'])

      time.sleep(1)

      scraped_data['popular_times'] = scrap_popular_times()

      if not 'reviews' in place:
        save_progress(key, scraped_data)
        continue
      
      #driver.save_screenshot('out.png');

      review_count = go_to_reviews()

      scraped_data['reviews'] = scrap_reviews(review_count, "Place {0}/{1}".format(i, len(place_details.keys())))

    except TimeoutException:
      # failed to load reviews
      scraped_data["scrap_interruption"] = { "type": "timeout" }
      print(" [Interrupted by TimeoutException]")
      continue
    except StaleElementReferenceException:
      # this is bad too
      scraped_data["scrap_interruption"] = { "type": "stale_element_reference" }
      print(" [Interrupted by StaleElementReferenceException]")
      continue
    except ReviewsNotLoading as e:
      log_interruption(place_details, key, e)
      break
    except Exception as e:
      # in case of a unexpected exception
      print(e)
      log_interruption(place_details, key, e)
      break
    finally:
      # save what we have so far
      save_progress(key, scraped_data)

  driver.close()

if __name__ == "__main__":
  main()
