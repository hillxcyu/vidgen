# Author:Hill YU(xcyu@)
"""Test cases catalog for the 20-scenario reference adherence benchmark suite.
Contains diverse ethnicities, demographics, framing types, reference generation prompts,
and prompt variants for Mode A (Optimized), Mode B (Simple), and Mode C (Task Parameter).
"""

from typing import Any, Dict, List

BENCHMARK_CASES: List[Dict[str, Any]] = [
    {
        "id": 1,
        "name": "East Asian Male (20s) - Alpine Skiing",
        "ethnicity": "East Asian",
        "demographics": "20-year-old East Asian male",
        "framing": "Headshot / Close-up",
        "framing_category": "Headshot",
        "action_summary": "Skiing in Hakuba",
        "ref_prompt": (
            "A clear, high-resolution portrait photograph of a 20-year-old East Asian male, "
            "wearing a stylish red and black alpine ski jacket and dark beanie, friendly confident expression, "
            "looking directly into the camera, sharp facial features, natural daylight against soft snowy mountain backdrop, photorealistic."
        ),
        "ref_studio_prompt": (
            "A clear, high-resolution portrait photograph of a 20-year-old East Asian male, "
            "wearing a stylish red and black alpine ski jacket and dark beanie, friendly confident expression, "
            "looking directly into the camera, sharp facial features, professional clean studio softbox lighting, "
            "isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) skiing in Hakuba",
        "mode_a_cinematic": (
            "Character A, continuous single take, dynamic cinematic tracking shot following the character "
            "skiing gracefully down a powdery slope on Hakuba Happo-One ridge, crisp alpine morning sunlight "
            "reflecting off the snow, dramatic Japanese Northern Alps in the background, sharp cinematic focus, photorealistic."
        ),
    },
    {
        "id": 2,
        "name": "Black Female (20s) - Track Sprinting",
        "ethnicity": "Black / African",
        "demographics": "20-year-old Black female athlete",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Sprinting on coastal track",
        "ref_prompt": (
            "Full-body portrait of a 20-year-old athletic Black female runner, natural short afro hair, "
            "wearing a bright neon yellow running windbreaker, dark compression tights, and running sneakers, "
            "confident athletic posture looking forward, crisp outdoor track lighting, photorealistic."
        ),
        "ref_studio_prompt": (
            "Full-body portrait of a 20-year-old athletic Black female runner, natural short afro hair, "
            "wearing a bright neon yellow running windbreaker, dark compression tights, and running sneakers, "
            "confident athletic posture looking forward, professional clean studio softbox lighting, "
            "isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) sprinting on an outdoor running track",
        "mode_a_cinematic": (
            "Character A, low-angle dynamic cinematic tracking shot racing alongside the character as she sprints "
            "explosively down a red running track next to the ocean, athletic stride, glistening skin in golden afternoon light, "
            "shallow depth of field, photorealistic 8k."
        ),
    },
    {
        "id": 3,
        "name": "Caucasian Male (30s) - Parisian Cafe",
        "ethnicity": "Caucasian",
        "demographics": "35-year-old Caucasian male",
        "framing": "Bust / Medium Portrait",
        "framing_category": "Medium",
        "action_summary": "Drinking coffee in Paris cafe",
        "ref_prompt": (
            "Bust portrait of a 35-year-old Caucasian male with neat short brown hair, trimmed beard, "
            "wearing a textured cream cable-knit wool sweater, relaxed friendly smile, natural soft window light "
            "in a charming rustic cafe setting, photorealistic."
        ),
        "ref_studio_prompt": (
            "Bust portrait of a 35-year-old Caucasian male with neat short brown hair, trimmed beard, "
            "wearing a textured cream cable-knit wool sweater, relaxed friendly smile, professional clean studio softbox lighting, "
            "isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) drinking coffee in a Parisian cafe",
        "mode_a_cinematic": (
            "Character A, slow medium dolly push-in shot of the character sitting by a sunlit window table "
            "in an elegant Parisian bistro, gently raising an espresso cup and taking a warm sip as morning street life "
            "blurs softly outside, cinematic warm palette."
        ),
    },
    {
        "id": 4,
        "name": "South Asian Female (20s) - Mumbai Market",
        "ethnicity": "South Asian",
        "demographics": "24-year-old South Asian female",
        "framing": "Headshot / Close-up",
        "framing_category": "Headshot",
        "action_summary": "Walking in Mumbai market",
        "ref_prompt": (
            "Close-up portrait photograph of a 24-year-old South Asian female with warm honey-brown eyes, radiant skin, "
            "wearing an emerald green and gold embroidered silk dupatta scarf draped gracefully, gentle welcoming smile, "
            "warm ambient lighting with colorful blurred market background, photorealistic."
        ),
        "ref_studio_prompt": (
            "Close-up portrait photograph of a 24-year-old South Asian female with warm honey-brown eyes, radiant skin, "
            "wearing an emerald green and gold embroidered silk dupatta scarf draped gracefully, gentle welcoming smile, "
            "professional clean studio softbox lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) walking through a colorful Mumbai market",
        "mode_a_cinematic": (
            "Character A, vibrant shallow depth-of-field tracking shot gliding backward in front of the character as she walks "
            "happily through a bustling Mumbai flower and spice market, golden hour backlight catching the silk fabric, "
            "dynamic festive ambiance, cinematic photorealism."
        ),
    },
    {
        "id": 5,
        "name": "Hispanic Male (40s) - Patagonia Trekking",
        "ethnicity": "Hispanic / Latino",
        "demographics": "42-year-old Hispanic male",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Hiking in Patagonia mountains",
        "ref_prompt": (
            "Full-body outdoor portrait of a 42-year-old Hispanic male mountaineer with weathered handsome features, "
            "wearing a rugged navy plaid flannel over-shirt, slate cargo hiking pants, brown leather hiking boots, "
            "and carrying a trail backpack with trekking poles, dramatic windswept mountain overlook, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) hiking across a mountain ridge in Patagonia",
        "mode_a_cinematic": (
            "Character A, majestic wide-angle cinematic drone shot rising and tracking alongside the character "
            "as he strides purposefully along a rugged Patagonian ridge line, dramatic granite peaks and turquoise glacial lakes "
            "unfolding in the panoramic distance, cinematic epic travel documentary style."
        ),
    },
    {
        "id": 6,
        "name": "East Asian Female (30s) - Rainy Shibuya",
        "ethnicity": "East Asian",
        "demographics": "30-year-old East Asian female",
        "framing": "Three-Quarter Shot",
        "framing_category": "Three-Quarter",
        "action_summary": "Walking in rainy Shibuya",
        "ref_prompt": (
            "Three-quarter portrait of a 30-year-old East Asian female with a sleek black bob haircut, "
            "wearing a tailored charcoal wool trench coat and minimalist silver jewelry, standing under soft city lights, "
            "cool evening mist, elegant poised gaze directly at camera, photorealistic."
        ),
        "ref_studio_prompt": (
            "Three-quarter portrait of a 30-year-old East Asian female with a sleek black bob haircut, "
            "wearing a tailored charcoal wool trench coat and minimalist silver jewelry, elegant poised gaze directly at camera, "
            "professional clean studio softbox lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) walking through rainy Shibuya at night",
        "mode_a_cinematic": (
            "Character A, cinematic slow-motion tracking shot following the character as she walks gracefully with a transparent umbrella "
            "through the iconic Shibuya crossing at night, neon billboards reflecting off rain-slicked asphalt, vibrant Tokyo city nightscape, "
            "anamorphic lens flare, photorealistic."
        ),
    },
    {
        "id": 7,
        "name": "Middle Eastern Male (20s) - Dubai Marina",
        "ethnicity": "Middle Eastern",
        "demographics": "26-year-old Middle Eastern male",
        "framing": "Headshot / Close-up",
        "framing_category": "Headshot",
        "action_summary": "Strolling along Dubai marina",
        "ref_prompt": (
            "Crisp close-up portrait of a 26-year-old Middle Eastern male with neatly groomed dark beard and sharp jawline, "
            "wearing a crisp white relaxed linen button-down shirt, confident friendly smile, bright Mediterranean daylight "
            "reflecting softly, modern architectural glass backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) strolling along Dubai marina promenade",
        "mode_a_cinematic": (
            "Character A, sun-drenched luxury tracking shot following the character as he walks casually along the Dubai marina boardwalk, "
            "glittering turquoise water and luxury yachts docked in background, towering futuristic skyscrapers under cloudless blue sky, "
            "crisp 4k commercial look."
        ),
    },
    {
        "id": 8,
        "name": "Black Male (30s) - Basketball Action",
        "ethnicity": "Black / African",
        "demographics": "32-year-old athletic Black male",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Playing basketball on court",
        "ref_prompt": (
            "Full-body athletic portrait of a 32-year-old Black male basketball player, athletic muscular build, "
            "wearing a red basketball jersey, black shorts, and white high-top basketball sneakers, holding a basketball at hip, "
            "outdoor urban streetball court at sunset, photorealistic."
        ),
        "ref_studio_prompt": (
            "Full-body athletic portrait of a 32-year-old Black male basketball player, athletic muscular build, "
            "wearing a red basketball jersey, black shorts, and white high-top basketball sneakers, holding a basketball at hip, "
            "professional clean studio lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) playing basketball on an outdoor court",
        "mode_a_cinematic": (
            "Character A, dynamic low-angle slow-motion action shot following the character as he drives past the defender, "
            "elevates smoothly toward the basketball rim, and slams down an emphatic two-handed dunk, chain-link fence and sunset sky "
            "in background, cinematic sports reel style."
        ),
    },
    {
        "id": 9,
        "name": "Southeast Asian Female (20s) - Amsterdam Cycling",
        "ethnicity": "Southeast Asian",
        "demographics": "25-year-old Southeast Asian female",
        "framing": "Bust / Medium Portrait",
        "framing_category": "Medium",
        "action_summary": "Cycling along Amsterdam canal",
        "ref_prompt": (
            "Medium bust portrait of a 25-year-old Southeast Asian female with lively expressive brown eyes and high ponytail, "
            "wearing a bright yellow waterproof rain jacket, commuter bicycle helmet, and casual scarf, friendly cheerful expression, "
            "quaint European canal bridge backdrop, photorealistic."
        ),
        "ref_studio_prompt": (
            "Medium bust portrait of a 25-year-old Southeast Asian female with lively expressive brown eyes and high ponytail, "
            "wearing a bright yellow waterproof rain jacket, commuter bicycle helmet, and casual scarf, friendly cheerful expression, "
            "professional clean studio softbox lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) riding a bicycle along an Amsterdam canal",
        "mode_a_cinematic": (
            "Character A, smooth bicycle-mounted tracking camera facing backward at the character as she pedals merrily along "
            "a tree-lined brick canal in Amsterdam, historic 17th-century canal houses and stone bridges gliding past, soft diffused European light, "
            "photorealistic travel vlog style."
        ),
    },
    {
        "id": 10,
        "name": "Caucasian Female (60s) - Botanical Reading",
        "ethnicity": "Caucasian",
        "demographics": "65-year-old Caucasian female",
        "framing": "Headshot / Close-up",
        "framing_category": "Headshot",
        "action_summary": "Reading in botanical garden",
        "ref_prompt": (
            "Gentle close-up portrait of a 65-year-old Caucasian female with distinguished silver-grey wavy hair, delicate wire-rimmed reading glasses, "
            "warm laugh lines around wise blue eyes, wearing an olive linen tunic, surrounded by lush botanical greenhouse greenery, "
            "soft dappled sunbeams, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) reading a book in a botanical garden greenhouse",
        "mode_a_cinematic": (
            "Character A, serene cinematic close-up with soft floating dust motes as the character turns a page of an antique hardcover book, "
            "glancing up with a warm peaceful smile surrounded by blooming purple orchids and lush tropical ferns in a Victorian glasshouse, "
            "warm cinematic golden lighting."
        ),
    },
    {
        "id": 11,
        "name": "South Asian Male (30s) - Grass Tennis",
        "ethnicity": "South Asian",
        "demographics": "34-year-old South Asian male",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Playing tennis on grass court",
        "ref_prompt": (
            "Full-body portrait of a 34-year-old athletic South Asian male tennis player, wearing classic white tennis polo shirt, "
            "white shorts, tennis wristbands, holding a modern graphite tennis racquet, standing ready on a manicured green grass tennis court, "
            "bright summer tournament sunshine, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) playing a tennis match on a grass court",
        "mode_a_cinematic": (
            "Character A, courtside high-speed tracking shot following the character as he sprints across the lush grass court, "
            "sets his footing with athletic precision, and strikes a blistering forehand winner down the line, chalk dust kicking up from baseline, "
            "broadcast sports cinematography."
        ),
    },
    {
        "id": 12,
        "name": "Hispanic Female (20s) - Oaxaca Street Festival",
        "ethnicity": "Hispanic / Latino",
        "demographics": "23-year-old Hispanic female",
        "framing": "Three-Quarter Shot",
        "framing_category": "Three-Quarter",
        "action_summary": "Dancing at street festival",
        "ref_prompt": (
            "Three-quarter portrait of a 23-year-old Hispanic female with long dark wavy hair adorned with festive ribbons, "
            "wearing a vibrant embroidered floral dress and denim cropped jacket, joyful radiant smile, colorful papel picado banners "
            "and colonial arches in background, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) dancing at a street festival in Oaxaca",
        "mode_a_cinematic": (
            "Character A, swirling 360-degree celebratory orbit camera circling the character as she dances joyfully in a cobblestone plaza, "
            "multicolored festival confetti floating through golden evening air, traditional musicians and warm string lights creating a magical festive aura, "
            "cinematic."
        ),
    },
    {
        "id": 13,
        "name": "Indigenous Male (30s) - Banff Overlook",
        "ethnicity": "Indigenous / Native",
        "demographics": "36-year-old Indigenous North American male",
        "framing": "Bust / Medium Portrait",
        "framing_category": "Medium",
        "action_summary": "Standing on mountain overlook",
        "ref_prompt": (
            "Bust portrait of a 36-year-old Indigenous North American male with strong regal facial features, long dark hair tied in a neat tie, "
            "wearing a brown shearling-lined leather jacket, calm thoughtful gaze looking toward the horizon, crisp Canadian Rockies mountain wind, "
            "sharp alpine light, photorealistic."
        ),
        "ref_studio_prompt": (
            "Bust portrait of a 36-year-old Indigenous North American male with strong regal facial features, long dark hair tied in a neat tie, "
            "wearing a brown shearling-lined leather jacket, calm thoughtful gaze looking toward camera, "
            "professional clean studio softbox lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) standing on a mountain cliff overlook in Banff",
        "mode_a_cinematic": (
            "Character A, epic slow push-in cinematic shot facing the character standing tall at the edge of a rocky cliff overlook, "
            "wind softly rustling his hair as the camera pulls slightly back to reveal the breathtaking turquoise waters of Lake Louise "
            "and snow-dusted pine valleys below, National Geographic documentary aesthetic."
        ),
    },
    {
        "id": 14,
        "name": "Black Female (40s) - Keynote Stage",
        "ethnicity": "Black / African",
        "demographics": "45-year-old Black female leader",
        "framing": "Headshot / Close-up",
        "framing_category": "Headshot",
        "action_summary": "Giving a keynote speech on stage",
        "ref_prompt": (
            "Close-up portrait of a 45-year-old Black female executive with radiant dark skin, wearing a modern sculptural royal blue blazer "
            "and sleek wireless lavalier earset microphone, poised confident and inspiring expression, soft professional stage lighting, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) delivering a keynote speech on stage",
        "mode_a_cinematic": (
            "Character A, cinematic slow camera push-in as the character delivers an inspiring keynote address on an auditorium stage, "
            "gesturing with authority, presentation screen and warm stage lighting in background, photorealistic."
        ),
    },
    {
        "id": 15,
        "name": "Caucasian Male (20s) - Hawaii Surfing",
        "ethnicity": "Caucasian",
        "demographics": "24-year-old Caucasian male surfer",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Walking into ocean with surfboard",
        "ref_prompt": (
            "Full-body portrait of a 24-year-old athletic Caucasian male surfer with sun-bleached tousled hair, sun-kissed skin, "
            "wearing a black neoprene surf vest and boardshorts, holding a custom white surfboard under his arm, standing on a golden sand beach, "
            "sparkling Pacific ocean breakers behind, photorealistic."
        ),
        "ref_studio_prompt": (
            "Full-body portrait of a 24-year-old athletic Caucasian male surfer with sun-bleached tousled hair, sun-kissed skin, "
            "wearing a black neoprene surf vest and boardshorts, holding a custom white surfboard under his arm, "
            "professional clean studio lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) walking into the ocean surf with a surfboard in Hawaii",
        "mode_a_cinematic": (
            "Character A, cinematic slow-motion tracking shot following the character from behind and side as he walks barefoot across wet sand "
            "into the crashing ocean whitewash, paddling out through breaking turquoise waves under a glowing golden Hawaiian sunset, "
            "photorealistic surf film style."
        ),
    },
    {
        "id": 16,
        "name": "East Asian Male (50s) - Kyoto Tea Ceremony",
        "ethnicity": "East Asian",
        "demographics": "55-year-old East Asian male tea master",
        "framing": "Bust / Medium Portrait",
        "framing_category": "Medium",
        "action_summary": "Preparing matcha tea in Kyoto",
        "ref_prompt": (
            "Medium bust portrait of a 55-year-old East Asian male with distinguished silver-black hair and serene mindful demeanor, "
            "wearing a traditional navy blue linen samue robe, sitting poised on tatami mats, peaceful natural courtyard garden visible through shoji screen, "
            "photorealistic."
        ),
        "clean_prompt": "Character A (reference image) preparing matcha green tea in a Kyoto tea house",
        "mode_a_cinematic": (
            "Character A, tranquil zen-like cinematic medium shot tracking the character's focused hands and serene face as he delicately whisks "
            "vibrant green matcha powder in a black ceramic chawan bowl with a bamboo chasen, gentle steam rising, soft bamboo garden light, "
            "contemplative masterpiece cinematography."
        ),
    },
    {
        "id": 17,
        "name": "Middle Eastern Female (30s) - Petra Ruins",
        "ethnicity": "Middle Eastern",
        "demographics": "32-year-old Middle Eastern female archaeologist",
        "framing": "Three-Quarter Shot",
        "framing_category": "Three-Quarter",
        "action_summary": "Exploring ancient ruins of Petra",
        "ref_prompt": (
            "Three-quarter portrait of a 32-year-old Middle Eastern female with warm olive complexion and expressive dark eyes, "
            "wearing a stylish khaki safari field vest over a terracotta linen shirt, leather cross-body satchel, gazing admiringly upward, "
            "ancient carved sandstone rock canyon backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) walking through the ancient ruins of Petra",
        "mode_a_cinematic": (
            "Character A, breathtaking cinematic crane reveal descending from the towering rose-red canyon walls of the Siq "
            "to follow the character as she emerges onto the sunlit plaza directly before the colossal ancient Treasury facade of Petra, "
            "dust particles glowing in sunlight, cinematic epic adventure."
        ),
    },
    {
        "id": 18,
        "name": "South Asian Female (40s) - Himalayan Sunrise Yoga",
        "ethnicity": "South Asian",
        "demographics": "40-year-old South Asian female yogi",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Performing yoga at sunrise",
        "ref_prompt": (
            "Full-body portrait of a 40-year-old South Asian female yoga practitioner with graceful poised posture, "
            "wearing terracotta and maroon athletic yoga wear, barefoot on a wooden mountain terrace, hands at heart center, "
            "first golden rays of sunrise breaking over distant misty Himalayan ridges, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) performing yoga at sunrise in the mountains",
        "mode_a_cinematic": (
            "Character A, graceful slow 180-degree panning profile shot following the character as she transitions fluidly "
            "from warrior pose into a serene standing balance pose on a cliffside wooden deck, morning mountain mist drifting below "
            "as golden sunlight illuminates snow-capped Himalayan peaks, peaceful transcendent cinematography."
        ),
    },
    {
        "id": 19,
        "name": "Hispanic Male (20s) - Vintage Havana",
        "ethnicity": "Hispanic / Latino",
        "demographics": "27-year-old Hispanic male",
        "framing": "Headshot / Close-up",
        "framing_category": "Headshot",
        "action_summary": "With vintage motorcycle in Havana",
        "ref_prompt": (
            "Close-up portrait of a 27-year-old Hispanic male with charismatic smile and curly dark hair, wearing a worn brown leather aviator jacket "
            "over a white cotton t-shirt, resting his arms casually on motorcycle handlebars, warm pastel colonial building facades in background, "
            "golden late-afternoon Havana light, photorealistic."
        ),
        "ref_studio_prompt": (
            "Close-up portrait of a 27-year-old Hispanic male with charismatic smile and curly dark hair, wearing a worn brown leather aviator jacket "
            "over a white cotton t-shirt, resting his arms casually forward, warm friendly expression, "
            "professional clean studio softbox lighting, isolated against a seamless solid plain white studio backdrop, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) standing next to a vintage motorcycle in Havana",
        "mode_a_cinematic": (
            "Character A, warm pastel-toned cinematic street tracking shot gliding past colorful weathered colonial buildings in Havana, "
            "tracking the character as he leans confidently against a classic motorcycle, nodding warmly to passersby as vintage turquoise cars "
            "cruise slowly past on the cobblestone avenue, nostalgic cinematic vibe."
        ),
    },
    {
        "id": 20,
        "name": "Scandinavian Female (20s) - Lapland Husky Sled",
        "ethnicity": "Caucasian",
        "demographics": "25-year-old Scandinavian female",
        "framing": "Full-Body Action Shot",
        "framing_category": "Full-Body",
        "action_summary": "Walking dogs in snowy Lapland",
        "ref_prompt": (
            "Full-body portrait of a 25-year-old Scandinavian female with braided blonde hair and rosy cheeks from the cold, "
            "wearing a thick traditional patterned Nordic wool sweater, dark insulated snow pants, fur-lined winter boots, and wool mittens, "
            "standing with two friendly Siberian huskies in a deep snow forest, frosted pine trees behind, photorealistic."
        ),
        "clean_prompt": "Character A (reference image) walking with sled dogs through a snowy pine forest in Lapland",
        "mode_a_cinematic": (
            "Character A, majestic wide-angle cinematic tracking shot following the character and her two energetic husky dogs "
            "as they jog through a pristine snow-covered pine forest in Lapland, fresh powder puffing beneath their footsteps under a soft twilight sky "
            "with faint emerald aurora borealis ribbons dancing overhead, fairy-tale winter realism."
        ),
    },
]

# 10 Representative cases covering diverse demographics and all framing categories
STUDIO_SUBSET_IDS = [1, 2, 3, 4, 6, 8, 9, 13, 15, 19]
