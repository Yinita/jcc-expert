# Round 3 Nature: manually labelled public gameplay

This batch contains 12 admitted, real public gameplay screenshots: 7 development images in `annotations.json`, and 5 sealed evaluation frames in `sealed_annotations.json`. The sealed labels and QA strip must remain unread by the training/development operator until code, models, thresholds, and input policies are frozen. `inventory.json` is safe to inspect before that point: it contains metadata and hashes, not numeric ground truth. The previous 38-image corpus was treated as consumed development data, not as new independent holdout data.

## Sources and grouping

- Development: [听雨猫-金铲铲教学 original full-game video](https://www.bilibili.com/video/BV1uCti6oEk7/), published 2026-09-04. Four frames at 120, 420, 720, and 1020 seconds, fixed 300-second spacing. They are one source group, not four matches. The public recording shows the 金铲铲 mobile interface with the shop at the bottom.
- Development: [游戏茶馆 original article on TapTap](https://www.taptap.cn/moment/840465181304686223), mirrored [by its Sohu account](https://m.sohu.com/a/1066710710_116126). One actual mobile preparation screenshot. The author describes an advance media playtest, so this is explicitly a pre-release media-test screenshot, not verified patch 18.6 footage.
- Development: [玩加电竞 original first-hand article](https://www.wanplus.cn/article/507000.html), published 2026-08-19. Two actual mobile preparation screenshots. The scoreboard is intentionally blurred; that field remains unknown. These also come from a pre-release media playtest.
- Sealed: [Kirito昊 original video](https://www.bilibili.com/video/BV1iX8462E3c/). One complete original video group. Its opening meme segment is excluded; gameplay frames use fixed 20-second spacing within the gameplay segment. Includes an equipment-selection overlay. No field values are reproduced in this document.
- Sealed: [熊六开花 original video](https://www.bilibili.com/video/BV1Z6tJ6REny/). One complete original video group. The author edited this video to a square crop of the right side of the mobile interface. Frames at fixed 20-second spacing are retained as visibility/abstention cases; this group is not described as full-HUD footage. No field values are reproduced in this document.

Exact patch and live/test server status cannot be established visually for the post-release public videos. Their patch is `null`, and their server status explicitly says unverified. Nature season confirmation uses visible Nature heroes, traits, charms, and source context. This batch contains no PC TFT footage, generated screenshots, array-guide boards, or reconstructed HUDs.

## Retrieval and authenticity

Bilibili HTML returned an access error, while its public metadata API and public player media URLs were accessible without authentication. The existing playable originals were downloaded normally. Source API endpoints, original video IDs, CIDs, timestamps, original video dimensions, video SHA-256 hashes, and retained local media paths are recorded in `sources.json`. Signed transient player URLs are not used as durable source references. FFmpeg extracted PNG frames directly from the public recordings; no compositing, inpainting, HUD recreation, or crop augmentation created additional samples.

Source image downloads are kept unchanged under the admitted filenames. The `candidates` directory includes rejected promotional images and intermediate QA assets; they are **not** samples and must not be included by recursive image globbing. The only admitted sample lists are the annotation manifests.

## Annotation method

Every admitted full image was personally opened with `view_image`. Only clearly visible values were labelled. Each field box was drawn around actual numeric glyphs, normalized as `[x, y, width, height]`, and manually checked through a crop QA strip. Chinese level suffixes and coin glyphs are outside the intended numeric boxes. A player level visible only in the own named little-legend badge is explicitly noted. Board capacity, another player's badge, or another player's HP is never substituted for the player's level or HP.

Unknown values remain `null`. `absent_fields` distinguishes fields that genuinely do not exist in that particular screen/crop from fields present but unreadable (for example, the blurred article scoreboard). Equipment-choice cards are not shop heroes. The shop always has five label slots: an actually empty slot is `{ "empty": true }`; a charm or unidentified/non-visible slot is `null` with explanatory notes. Hero names were manually linked to official first-star IDs in `nature_facts.json`; visible shop heroes are not assumed to share the displayed card star count.

`negative_boxes` contains actual visible non-target numbers such as XP purchase prices, refresh prices, stage countdowns, streak counts, XP progress, and board capacity. They are not boxes around an unknown field treated as false. No recognizer, OCR proposal generator, trainable model, or model feedback was run during source selection or manual annotation.

## Duplicate and independence checks

All 12 admitted decoded RGB SHA-256 hashes are distinct from one another and from the 38 entries in `work/expanded_eval/corpus_inventory.json`. Both original-file and decoded-pixel hashes are recorded. Similar grass-arena article images were visually compared with the closest old candidates and depict different units/stages/scenes. Exact equality cannot prove statistical independence, and different media articles from one Tencent playtest event are not asserted to be different matches. Evaluation must group by original article/video ID, never by image/frame, and report both frame counts and source-group counts.

The fixed-interval video frames are temporal observations from the same video, not independent outcomes. This batch supports UI recognition and visibility validation; it cannot establish win-rate or first-place probabilities.

## Remaining coverage gaps

This batch adds full mobile preparation HUDs, bottom and top shop positions, an early-game shop, carousel field absence, intentional scoreboard blur, equipment-selection coverage, and source-side partial crops. It does not yet add a verified patch 18.6 formal-server augment-selection screen. A title or patch publication date alone is insufficient to assign the exact patch to a recorded match.
