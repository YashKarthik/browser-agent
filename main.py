from typing import List, Union
from playwright.sync_api import sync_playwright, Locator, ElementHandle
import openai
from time import sleep

"""
Next steps:
    - [X] Create a structure that maps integer ids (generated by us) to Locator objects.
    - [X] Do something similar for simplified version of the elements
    - We send the simplified view, list of these elements to GPT.
    - GPT responds with ACTION and ID.
    - Create a runner loop to refresh buffer elements on each page load.
    - Where ACTION corresponds to actions we've implemented.
        - [X]: implement different actions (CLICK, TYPE, ENTER/SUBMIT)
    - [X] We perform the action on an element by grabbing it from our struct.
    - [X] Since the struct contains `Locator`s, we can do the action on it directly using Playwright.

Later:
    - Internal monologue.
    - Integrate voice with whisper
"""

prompt_template = """
You are an agent controlling a browser. You are given:

    (1) an objective that you are trying to achieve
    (2) the URL of your current web page
    (3) a simplified text description of what's visible in the browser window (more on that below)

You can issue these commands:
    SCROLL UP - scroll up one page
    SCROLL DOWN - scroll down one page
    CLICK X - click on a given element. You can only click on links, buttons, and inputs!
    TYPE X "TEXT" - type the specified text into the input with id X
    TYPESUBMIT X "TEXT" - same as TYPE above, except then it presses ENTER to submit the form

The format of the browser content is highly simplified; all formatting elements are stripped.
Interactive elements such as links, inputs, buttons are represented like this:

    <link id=1>text</link>
    <button id=2>text</button>
    <input id=3>text</input>

Images are rendered as their alt text like this:

    <img id=4 alt=""/>

Based on your given objective, issue whatever command you believe will get you closest to achieving your goal.
You always start on Duckduckgo; you should submit a search query to Duckduckgo that will take you to the best page for
achieving your objective. And then interact with that page to achieve your objective.

If you find yourself on Duckduckgo and there are no search results displayed yet, you should probably issue a command 
like "TYPESUBMIT 7 "search query"" to get to a more useful page.

Then, if you find yourself on a Duckduckgo search results page, you might issue the command "CLICK 24" to click
on the first link in the search results. (If your previous command was a TYPESUBMIT your next command should
probably be a CLICK.)

Don't try to interact with elements that you can't see.

Here are some examples:

    EXAMPLE 1:
        ==================================================
CURRENT BROWSER CONTENT:
    ------------------
<link id=1>About</link>
<link id=2>Store</link>
<link id=3>Gmail</link>
<link id=4>Images</link>
<link id=5>(Google apps)</link>
<link id=6>Sign in</link>
<img id=7 alt="(Google)"/>
<input id=8 alt="Search"></input>
<button id=9>(Search by voice)</button>
<button id=10>(Google Search)</button>
<button id=11>(I'm Feeling Lucky)</button>
<link id=12>Advertising</link>
<link id=13>Business</link>
<link id=14>How Search works</link>
<link id=15>Carbon neutral since 2007</link>
<link id=16>Privacy</link>
<link id=17>Terms</link>
<text id=18>Settings</text>
------------------
OBJECTIVE: Find a 2 bedroom house for sale in Anchorage AK for under $750k
CURRENT URL: https://www.duckduckgo.com/
YOUR COMMAND: 
    TYPESUBMIT 8 "anchorage redfin"
==================================================

EXAMPLE 2:
    ==================================================
CURRENT BROWSER CONTENT:
    ------------------
<link id=1>About</link>
<link id=2>Store</link>
<link id=3>Gmail</link>
<link id=4>Images</link>
<link id=5>(Google apps)</link>
<link id=6>Sign in</link>
<img id=7 alt="(Google)"/>
<input id=8 alt="Search"></input>
<button id=9>(Search by voice)</button>
<button id=10>(Google Search)</button>
<button id=11>(I'm Feeling Lucky)</button>
<link id=12>Advertising</link>
<link id=13>Business</link>
<link id=14>How Search works</link>
<link id=15>Carbon neutral since 2007</link>
<link id=16>Privacy</link>
<link id=17>Terms</link>
<text id=18>Settings</text>
------------------
OBJECTIVE: Make a reservation for 4 at Dorsia at 8pm
CURRENT URL: https://www.duckduckgo.com/
YOUR COMMAND: 
    TYPESUBMIT 8 "dorsia nyc opentable"
==================================================

EXAMPLE 3:
    ==================================================
CURRENT BROWSER CONTENT:
    ------------------
<button id=1>For Businesses</button>
<button id=2>Mobile</button>
<button id=3>Help</button>
<button id=4 alt="Language Picker">EN</button>
<link id=5>OpenTable logo</link>
<button id=6 alt ="search">Search</button>
<text id=7>Find your table for any occasion</text>
<button id=8>(Date selector)</button>
<text id=9>Sep 28, 2022</text>
<text id=10>7:00 PM</text>
<text id=11>2 people</text>
<input id=12 alt="Location, Restaurant, or Cuisine"></input> 
<button id=13>Let’s go</button>
<text id=14>It looks like you're in Peninsula. Not correct?</text> 
<button id=15>Get current location</button>
<button id=16>Next</button>
------------------
OBJECTIVE: Make a reservation for 4 for dinner at Dorsia in New York City at 8pm
CURRENT URL: https://www.opentable.com/
YOUR COMMAND: 
    TYPESUBMIT 12 "dorsia new york city"
==================================================

The current browser content, objective, and current URL follow. Reply with your next command to the browser.

CURRENT BROWSER CONTENT:
    ------------------
$browser_content
------------------

OBJECTIVE: $objective
CURRENT URL: $url
PREVIOUS COMMAND: $previous_command
YOUR COMMAND:
"""

class Crawler:
    def __init__(self):
        p = sync_playwright().start()
        self.browser = p.chromium.launch(headless=False)
        self.page = self.browser.new_page()
        self.elements_buffer: dict[int, Union[Locator, ElementHandle]] = {}
        self.simplified_elements_buffer: dict[int, str] = {}

    def go_to_page(self, url: str):
        self.page.goto(url)

    def add_elements_to_buffer(self):
        page_html = self.page.query_selector("body")
        if page_html is None:
            print("page_html is None")
            exit(1)

        links = page_html.query_selector_all("a")
        buttons = page_html.query_selector_all("button")
        images = page_html.query_selector_all("img")
        inputs = page_html.query_selector_all("input")

        i = 0
        for link in links:
            text = link.inner_text().strip().replace("\n", "").replace("  ", " ")
            if text == "":
                continue

            self.elements_buffer[i] = link
            self.simplified_elements_buffer[i] = "<link id={0}>{1}</link>".format(i, text)
            i += 1

        for button in buttons:
            text = button.inner_text().strip().replace("\n", "").replace("  ", " ")
            if text == "":
                continue

            self.elements_buffer[i] = button
            self.simplified_elements_buffer[i] = "<button id={0}>{1}</button>".format(i, text)
            i += 1

        for image in images:
            text = image.get_attribute("alt")
            if text == "":
                continue

            self.elements_buffer[i] = image
            self.simplified_elements_buffer[i] = "<img id={0} alt=\"{1}\" />".format(i, text)
            i += 1

        for input in inputs:
            t1 = input.get_attribute("title")
            t2 = input.get_attribute("alt")
            t3 = input.get_attribute("placeholder")
            t4 = input.get_attribute("aria-label")
            t5 = input.get_attribute("type")
            t6 = input.get_attribute("name")
            if t5 == "hidden": continue;

            text = t1 if t1 else " " + t2 if t2 else " " + t3 if t3 else " " + t4 if t4 else " " + t5 if t5 else " " + t6 if t6 else " "

            self.elements_buffer[i] = input
            self.simplified_elements_buffer[i] = "<input id={0} alt=\"{1}\" />".format(i, text)
            i += 1

    def refresh_elements_buffer(self):
        self.elements_buffer.clear()
        self.simplified_elements_buffer.clear()
        self.add_elements_to_buffer()

    def click(self, id: int):
        self.elements_buffer[id].click()

    def type_text(self, id: int, text: str):
        self.elements_buffer[id].fill(text)
        self.elements_buffer[id].press("Enter")

if __name__ == "__main__":
    crawler = Crawler()
    crawler.go_to_page("https://wikipedia.com")
    crawler.add_elements_to_buffer()

    while True:

        for i in (crawler.simplified_elements_buffer.values()):
            print(i)

        print("\n")
        id = int(input("Enter id: "))
        if id == -1:
            print("Quitting...")
            break

        q = str(input("Enter query (if any): "))
        if q == "":
            crawler.click(id)
        else: crawler.type_text(id, q)

        print("Crawling page...\n---------------------------------------------\n\n\n")
        sleep(7)
        crawler.refresh_elements_buffer()

    crawler.browser.close()
