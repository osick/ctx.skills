#!/usr/bin/env python3
"""Generate NIAH context files with structured needle types inspired by MM-NIAH.

Supports three needle types from the MM-NIAH benchmark (https://mm-niah.github.io/):

  retrieval  — A single factual statement is hidden in filler text.
               The question asks to retrieve the fact.
  counting   — Multiple "the little penguin counted N needles" statements
               are scattered through the context. The question asks to list all counts.
  reasoning  — Multiple related comparative/ordering statements are embedded.
               The question requires combining them to infer an answer.

Legacy mode (--secret) embeds a raw string in plain-text filler (no JSON).

Usage:
    # MM-NIAH needle types (output is JSON with context, question, answer, metadata)
    python generate_context.py --size 10000 --needle-type retrieval
    python generate_context.py --size 5000  --needle-type counting --seed 42 --output ctx.json
    python generate_context.py --size 5000  --needle-type reasoning --depth 0.5

    # Legacy plain-text mode
    python generate_context.py --size 10000 --secret "The answer is 42"
"""
import argparse
import json
import os
import random
import string
import sys
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Filler text generation — coherent prose paragraphs
# ---------------------------------------------------------------------------

# Grammatically correct, topically diverse paragraphs.  Each is ~60-80 words.
# The generator shuffles and repeats them to reach the target token count.
# Using real coherent text avoids tripping LLM safety classifiers that flag
# random-looking or semantically incoherent input as adversarial.
_PARAGRAPHS: list[str] = [
    (
        "The sun rose slowly over the wide green valley, casting long shadows "
        "across the fields. A narrow river wound its way between ancient oak "
        "trees, and birds sang from the highest branches. The morning dew still "
        "clung to every blade of grass, and the scent of wildflowers drifted "
        "through the cool air. A farmer walked along the dirt path toward his "
        "barn, carrying a wooden bucket in each hand."
    ),
    (
        "In the small village square, the baker had already opened his shop. "
        "The smell of fresh bread filled the narrow cobblestone street, drawing "
        "customers from their homes. Children ran past the old stone fountain, "
        "laughing and calling to each other. A cat dozed on a sunny windowsill "
        "while merchants arranged colorful fruit on wooden market stalls. "
        "Somewhere nearby, a clock tower chimed eight times."
    ),
    (
        "Researchers at the university published a new study about the migration "
        "patterns of arctic terns. These remarkable birds travel thousands of "
        "miles each year between the poles. The team used satellite tracking data "
        "collected over several decades to map precise flight routes and rest "
        "stops. Their findings suggest that climate change has shifted traditional "
        "migration pathways farther north than previously recorded."
    ),
    (
        "The museum downtown recently opened an exhibit featuring pottery and "
        "tools from a Bronze Age settlement discovered near the coast last summer. "
        "Archaeologists believe the site was once a thriving trade hub connecting "
        "inland farming communities with coastal fishing villages. The collection "
        "includes delicate gold jewelry, woven textiles, and carved bone ornaments "
        "that reveal a surprisingly sophisticated artistic tradition."
    ),
    (
        "Every Tuesday afternoon, the community library hosted a reading group "
        "for retired teachers. They gathered in the upstairs meeting room, each "
        "bringing a cup of tea and a well-worn paperback. Discussions ranged from "
        "modern fiction to classic poetry, and disagreements were always friendly. "
        "The librarian often joined them during her break, contributing thoughtful "
        "observations about narrative structure and character development."
    ),
    (
        "The annual conference on environmental policy attracted delegates from "
        "forty countries. They discussed strategies for reducing carbon emissions "
        "and protecting biodiversity in vulnerable ecosystems. Several proposals "
        "focused on reforestation programs and sustainable agriculture techniques "
        "that could be implemented within five years. Others emphasized the "
        "importance of international cooperation and shared funding models."
    ),
    (
        "At the edge of town, an old railway bridge crossed the river. Trains "
        "had not used the line for decades, and the iron structure was slowly "
        "rusting. Local children sometimes walked along the tracks, balancing on "
        "the rails with outstretched arms. The town council debated whether to "
        "restore the bridge as a pedestrian walkway or dismantle it entirely "
        "and sell the metal for scrap."
    ),
    (
        "The kitchen garden behind the cottage produced more vegetables than the "
        "family could eat. Rows of tomatoes, beans, and lettuce stretched from "
        "the back door to the fence. Every Saturday morning, the surplus was "
        "loaded into baskets and taken to the farmers market. Neighbors often "
        "stopped by during the week to trade eggs or homemade jam for a bag of "
        "fresh herbs or a bundle of carrots."
    ),
    (
        "Marine biologists conducted a survey of coral reefs along the eastern "
        "coastline. They documented over three hundred species of fish and "
        "identified several areas where bleaching had damaged large sections of "
        "the reef. Water temperature readings confirmed a gradual warming trend "
        "over the past fifteen years. The team recommended establishing protected "
        "zones to allow the most affected areas to recover naturally."
    ),
    (
        "The old clock maker worked alone in his narrow workshop on Bridge Street. "
        "Shelves lined every wall, filled with gears, springs, and half-finished "
        "mechanisms. He repaired watches that other shops had given up on, using "
        "tools that his grandfather had made by hand. Customers sometimes waited "
        "months for their timepieces, but the results were always worth the wait. "
        "His reputation extended well beyond the borders of the county."
    ),
    (
        "A team of geologists mapped the underground cave system beneath the "
        "limestone hills north of the valley. They discovered a network of tunnels "
        "stretching over twelve kilometers, with several large chambers containing "
        "stalactites and underground pools. Samples of mineral deposits were sent "
        "to the laboratory for analysis. Preliminary results indicated the caves "
        "had formed over a period of roughly two million years."
    ),
    (
        "The school orchestra rehearsed every Wednesday evening in the main hall. "
        "Thirty-two students played a mix of strings, woodwinds, and percussion "
        "instruments. Their conductor, a retired professional cellist, pushed "
        "them hard but always with encouragement. They were preparing for a "
        "spring concert that would feature pieces by Dvorak and Grieg. Tickets "
        "had already sold out weeks before the performance date."
    ),
    (
        "Historians studying medieval trade routes found new evidence in a "
        "collection of merchant letters preserved in a monastery archive. The "
        "documents described shipments of wool, tin, and dried fish moving between "
        "ports along the northern coast. Prices, delivery dates, and the names of "
        "trading partners were recorded in careful detail. The letters provided a "
        "vivid picture of everyday commercial life in the fourteenth century."
    ),
    (
        "The city park covered nearly forty hectares and contained walking trails, "
        "a boating lake, and a botanical garden. On warm weekends, families spread "
        "blankets on the grass and ate picnic lunches under the shade of mature "
        "chestnut trees. Joggers circled the lake on a paved path while ducks "
        "paddled near the reeds. A small cafe near the east entrance served "
        "sandwiches and cold drinks throughout the afternoon."
    ),
    (
        "Engineers at the power plant monitored water levels in the reservoir "
        "throughout the dry season. Rainfall had been below average for three "
        "consecutive months, and the storage capacity dropped to sixty percent. "
        "Conservation measures were introduced, including reduced irrigation "
        "allocations for agricultural users downstream. Weekly reports were sent "
        "to the regional water authority, which coordinated supply across several "
        "neighboring districts to prevent shortages."
    ),
    (
        "The pottery workshop occupied a converted warehouse near the harbor. "
        "Students learned to shape clay on a spinning wheel, glaze their work, "
        "and fire it in a gas kiln. The instructor demonstrated each technique "
        "slowly, explaining the importance of consistent pressure and timing. "
        "Finished pieces dried on wooden racks along the far wall, waiting to "
        "be collected at the end of the six-week course."
    ),
    (
        "Astronomers at the mountain observatory captured detailed images of a "
        "distant galaxy using a newly upgraded telescope. The photographs revealed "
        "spiral arms containing clusters of young blue stars surrounded by clouds "
        "of interstellar gas. Data from the observation will help scientists "
        "understand how galaxies evolve over billions of years. The results were "
        "submitted to an international journal for peer review."
    ),
    (
        "The ferry crossed the strait twice a day, carrying passengers, vehicles, "
        "and cargo between the mainland and the island. The journey took about "
        "ninety minutes in calm weather but could stretch to two hours during "
        "winter storms. Most travelers stood on the upper deck to watch the "
        "coastline recede and the island gradually come into view. Seagulls "
        "followed the boat, hoping for scraps from the onboard cafeteria."
    ),
    (
        "A local carpenter built custom furniture using timber from sustainably "
        "managed forests. Each piece was designed to order, with the customer "
        "choosing the type of wood, dimensions, and finish. His workshop was "
        "filled with the pleasant smell of freshly cut oak and cedar. He preferred "
        "traditional joinery methods over modern adhesives, believing that "
        "well-made joints lasted longer and looked better with age."
    ),
    (
        "The veterinary clinic on Park Road treated everything from household "
        "pets to farm animals. On a typical morning, the waiting room held dogs, "
        "cats, a rabbit, and occasionally a parrot. The head veterinarian had "
        "practiced for over twenty years and still enjoyed the variety of cases. "
        "Emergency calls from nearby farms often arrived in the early hours, "
        "requiring quick decisions and steady hands in difficult conditions."
    ),
]


def _filler_words(count: int, max_len: int, rng: random.Random) -> list[str]:
    """Build a list of *count* words from coherent paragraphs.

    Paragraphs are shuffled and repeated until the target is reached.
    *max_len* filters individual words (for legacy --wordlength support).
    """
    # Build a large pool by shuffling and repeating paragraphs
    paragraphs = list(_PARAGRAPHS)
    words: list[str] = []
    while len(words) < count:
        rng.shuffle(paragraphs)
        for para in paragraphs:
            words.extend(para.split())
            if len(words) >= count:
                break

    words = words[:count]

    # Apply wordlength filter only when explicitly constrained below default
    if max_len < 10:
        words = [w for w in words if len(w) <= max_len]
        # If heavy filtering reduced count too much, pad with short words
        short_words = ["the", "and", "was", "for", "that", "with", "from",
                       "this", "but", "not", "are", "his", "her", "they",
                       "been", "have", "had", "one", "our", "all", "can"]
        short_pool = [w for w in short_words if len(w) <= max_len]
        if not short_pool:
            short_pool = ["a"]
        while len(words) < count:
            words.append(rng.choice(short_pool))

    return words


# ---------------------------------------------------------------------------
# Needle generators
# ---------------------------------------------------------------------------

# -- Retrieval ---------------------------------------------------------------

_RETRIEVAL_TEMPLATES = [
    ("The special magic {city} number is: {number}.",
     "What is the special magic {city} number?", "{number}"),
    ("The capital of {country} was secretly changed to {city} in {year}.",
     "What was the capital of {country} secretly changed to?", "{city}"),
    ("The secret password for the {place} vault is {code}.",
     "What is the secret password for the {place} vault?", "{code}"),
    ("Professor {name} discovered that {element} has exactly {number} isotopes.",
     "How many isotopes does {element} have according to Professor {name}?", "{number}"),
    ("The {color} key unlocks room {number} on the {ordinal} floor.",
     "Which room does the {color} key unlock?", "room {number} on the {ordinal} floor"),
]

_CITIES = ["Berlin", "Tokyo", "Nairobi", "Oslo", "Lima", "Dhaka", "Quito", "Riga"]
_COUNTRIES = ["Lumoria", "Zephyria", "Brontalia", "Verdania", "Crestonia"]
_PLACES = ["northern", "eastern", "crystal", "midnight", "ancient", "golden"]
_NAMES = ["Albrecht", "Nakamura", "Okonkwo", "Petrovic", "Ramirez", "Chen"]
_ELEMENTS = ["Yttrium", "Hafnium", "Thulium", "Ruthenium", "Osmium", "Iridium"]
_COLORS = ["crimson", "azure", "emerald", "amber", "violet", "silver"]
_ORDINALS = ["third", "seventh", "twelfth", "fifth", "ninth"]


def _gen_retrieval(rng: random.Random):
    tpl_needle, tpl_q, tpl_a = rng.choice(_RETRIEVAL_TEMPLATES)
    vals = {
        "city": rng.choice(_CITIES),
        "country": rng.choice(_COUNTRIES),
        "place": rng.choice(_PLACES),
        "name": rng.choice(_NAMES),
        "element": rng.choice(_ELEMENTS),
        "color": rng.choice(_COLORS),
        "ordinal": rng.choice(_ORDINALS),
        "number": str(rng.randint(10, 9999)),
        "year": str(rng.randint(1900, 2099)),
        "code": "".join(rng.choices(string.ascii_uppercase + string.digits, k=8)),
    }
    needle = tpl_needle.format(**vals)
    question = tpl_q.format(**vals)
    answer = tpl_a.format(**vals)
    return [needle], question, answer


# -- Counting ----------------------------------------------------------------

def _gen_counting(rng: random.Random, num_needles: int = None):
    if num_needles is None: num_needles = rng.randint(5, 8)
    counts = [rng.randint(1, 100) for _ in range(num_needles)]
    animals =["bacteria","bee","flea","hummingbird"]
    needles = [f"A {animals[rng.randint(0,3)]} counted {c} snowflakes." for c in counts]+["The elephant counted 1 bird."]
    question = "List all the counts of things that a little animal reported."
    answer = counts
    return needles, question, answer


# -- Reasoning ---------------------------------------------------------------

_REASONING_SCENARIOS = [
    # (template_fn) -> (needles, question, answer)
    "race",
    "price",
    "height",
    "temperature",
    "age",
]


def _gen_reasoning_race(names: list[str], rng: random.Random):
    rng.shuffle(names)
    order = names[:3]  # 1st, 2nd, 3rd
    needles = [
        f"{order[0]} finished the race before {order[1]}.",
        f"{order[1]} finished the race before {order[2]}.",
        f"{order[0]} was the first to finish the race.",
    ]
    question = "Wer war der Zweite im Rennen?"
    answer = order[1]
    return needles, question, answer


def _gen_reasoning_price(items: list[str], rng: random.Random):
    rng.shuffle(items)
    ranked = items[:3]  # most expensive to least
    needles = [
        f"The price of {ranked[0]} is higher than the {ranked[1]}.",
        f"{ranked[1]} costs more than {ranked[2]}.",
        f"The price of {ranked[2]} is the lowest of all.",
    ]
    question = "Which item is the most expensive?"
    answer = ranked[0]
    return needles, question, answer


def _gen_reasoning_height(names: list[str], rng: random.Random):
    rng.shuffle(names)
    order = names[:3]  # tallest to shortest
    needles = [
        f"{order[0]} is larger than {order[1]}.",
        f"{order[1]} is much huger than {order[2]}.",
        f"{order[2]} is the biggest of the three.",
    ]
    question = "Who is the tallest?"
    answer = order[0]
    return needles, question, answer


def _gen_reasoning_temperature(cities: list[str], rng: random.Random):
    rng.shuffle(cities)
    order = cities[:3]  # hottest to coldest
    needles = [
        f"{order[0]} is warmer than {order[1]}.",
        f"{order[1]} is warmer than {order[2]}.",
        f"{order[2]} recorded the lowest temperature.",
    ]
    question = "Which city is the warmest?"
    answer = order[0]
    return needles, question, answer


def _gen_reasoning_age(names: list[str], rng: random.Random):
    rng.shuffle(names)
    order = names[:3]  # oldest to youngest
    needles = [
        f"{order[0]} is older than {order[1]}.",
        f"{order[2]} is the youngest of the three.",
        f"{order[1]} is younger than {order[0]} but older than {order[2]}.",
    ]
    question = "Who is the oldest?"
    answer = order[0]
    return needles, question, answer


_REASONING_ITEMS = ["phone", "tablet", "headphones", "laptop", "camera", "speaker"]
_REASONING_NAMES = ["Xiaoming", "Xiaohong", "Xiaoqiang", "Xiaoli", "Xiaowei", "Xiaofang"]

_REASONING_FNS = {
    "race": lambda rng: _gen_reasoning_race(list(_REASONING_NAMES), rng),
    "price": lambda rng: _gen_reasoning_price(list(_REASONING_ITEMS), rng),
    "height": lambda rng: _gen_reasoning_height(list(_REASONING_NAMES), rng),
    "temperature": lambda rng: _gen_reasoning_temperature(list(_CITIES), rng),
    "age": lambda rng: _gen_reasoning_age(list(_REASONING_NAMES), rng),
}


def _gen_reasoning(rng: random.Random):
    scenario = rng.choice(_REASONING_SCENARIOS)
    return _REASONING_FNS[scenario](rng)


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------

def _insert_needles_at_depths(
    filler: list[str],
    needles: list[str],
    depth: Optional[float],
    rng: random.Random,
) -> tuple[list[str], list[float]]:
    """Insert needle sentences into filler word list, return (tokens, depths).

    Each needle is inserted as a sentence surrounded by filler words.
    """
    result = list(filler)
    placed_depths = []
    total = len(result)

    if depth is not None:
        # All needles around the requested depth (spread +-5%)
        positions = sorted(
            max(1, min(total - 1, int(total * (depth + rng.uniform(-0.05, 0.05)))))
            for _ in needles
        )
    else:
        # Spread needles evenly across 10%-90% of context
        n = len(needles)
        positions = [
            max(1, int(total * (0.1 + 0.8 * i / max(1, n - 1))))
            for i in range(n)
        ]
        if n == 1:
            positions = [max(1, int(total * rng.uniform(0.1, 0.9)))]

    # Insert in reverse order so earlier indices stay valid
    for needle, pos in sorted(zip(needles, positions), key=lambda x: -x[1]):
        needle_tokens = needle.split()
        for j, tok in enumerate(needle_tokens):
            result.insert(pos + j, tok)
        placed_depths.append(pos / total if total > 0 else 0.5)

    placed_depths.reverse()  # match original needle order
    return result, placed_depths


def generate_needle_context(
    size: int,
    needle_type: str,
    wordlength: int = 10,
    depth: Optional[float] = None,
    seed: Optional[int] = None,
) -> dict:
    """Generate a NIAH context with structured needles.

    Returns a dict with: context, question, answer, needles, placed_depth,
    context_length, needle_type.
    """
    rng = random.Random(seed)

    generators = {
        "retrieval": _gen_retrieval,
        "counting": _gen_counting,
        "reasoning": _gen_reasoning,
    }
    needles, question, answer = generators[needle_type](rng)

    # Estimate filler needed
    needle_token_count = sum(len(n.split()) for n in needles)
    filler_count = max(0, size - needle_token_count)
    filler = _filler_words(filler_count, wordlength, rng)

    tokens, placed_depths = _insert_needles_at_depths(filler, needles, depth, rng)
    context = " ".join(tokens)

    return {
        "context": context,
        "question": question,
        "answer": answer,
        "needles": needles,
        "placed_depth": placed_depths,
        "context_length": len(context.split()),
        "needle_type": needle_type,
    }


# ---------------------------------------------------------------------------
# Sandbox writer
# ---------------------------------------------------------------------------

_CHUNK_SIZE = 500  # tokens per file


def write_sandbox(data: dict, sandbox_root: str) -> None:
    """Write NIAH data as a sandbox directory for RLM / direct-prompt testing.

    Creates:
        sandbox_root/
            niah.json          — metadata (question, answer, needles, depths; NO context)
            sandbox/
                chunk_0000.txt — first ~500-token chunk of the context
                chunk_0001.txt — …
    """
    root = Path(sandbox_root)
    sb_dir = root / "sandbox"
    sb_dir.mkdir(parents=True, exist_ok=True)

    context = data["context"]
    tokens = context.split()

    # Split into chunks
    chunks: list[str] = []
    for i in range(0, len(tokens), _CHUNK_SIZE):
        chunk_tokens = tokens[i : i + _CHUNK_SIZE]
        chunks.append(" ".join(chunk_tokens))

    # Write chunk files
    filenames: list[str] = []
    for i, chunk in enumerate(chunks):
        fname = f"chunk_{i:04d}.txt"
        (sb_dir / fname).write_text(chunk, encoding="utf-8")
        filenames.append(fname)

    # Write niah.json (metadata only, no context blob)
    meta = {k: v for k, v in data.items() if k != "context"}
    meta["sandbox_files"] = filenames
    (root / "niah.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Legacy plain-text mode
# ---------------------------------------------------------------------------

def generate_context_legacy(
    size: int,
    secret: str,
    wordlength: int = 10,
    seed: Optional[int] = None,
) -> str:
    rng = random.Random(seed)
    secret_tokens = secret.split()
    filler_count = max(0, size - len(secret_tokens))
    filler = _filler_words(filler_count, wordlength, rng)

    lo = max(1, int(len(filler) * 0.1))
    hi = max(lo + 1, int(len(filler) * 0.9))
    insert_pos = rng.randint(lo, hi)

    for i, token in enumerate(secret_tokens):
        filler.insert(insert_pos + i, token)

    return " ".join(filler)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate NIAH context files with structured needle types (MM-NIAH inspired)"
    )
    parser.add_argument(
        "--size", type=int, required=True,
        help="Approximate context size in tokens",
    )

    # Needle type mode (MM-NIAH)
    parser.add_argument(
        "--needle-type", type=str, default=None,
        choices=["retrieval", "counting", "reasoning"],
        dest="needle_type",
        help="MM-NIAH needle type: retrieval, counting, or reasoning",
    )
    parser.add_argument(
        "--depth", type=float, default=None,
        help="Needle placement depth (0.0=start, 1.0=end). Omit for automatic spread.",
    )

    # Legacy mode
    parser.add_argument(
        "--secret", type=str, default=None,
        help="(Legacy) Plain secret string to embed in filler text",
    )

    # Sandbox mode
    parser.add_argument(
        "--sandbox", type=str, default=None,
        help="Write context as chunked files to DIR/sandbox/ and metadata to DIR/niah.json",
    )

    # Common
    parser.add_argument("--wordlength", type=int, default=10,
                        help="Maximum filler word length (default: 10)")
    parser.add_argument("--output", type=str, default=None,
                        help="Output file (default: stdout)")
    parser.add_argument("--seed", type=int, default=None,
                        help="Random seed for reproducibility")
    args = parser.parse_args()

    if not args.needle_type and not args.secret:
        parser.error("Either --needle-type or --secret is required")

    if args.secret and not args.needle_type:
        # Legacy plain-text mode
        content = generate_context_legacy(
            size=args.size, secret=args.secret,
            wordlength=args.wordlength, seed=args.seed,
        )
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            print(content)
    else:
        # MM-NIAH structured mode
        data = generate_needle_context(
            size=args.size, needle_type=args.needle_type,
            wordlength=args.wordlength, depth=args.depth, seed=args.seed,
        )

        if args.sandbox:
            write_sandbox(data, args.sandbox)
        else:
            output_text = json.dumps(data, indent=2, ensure_ascii=False)
            if args.output:
                with open(args.output, "w", encoding="utf-8") as f:
                    f.write(output_text)
            else:
                print(output_text)


if __name__ == "__main__":
    main()
