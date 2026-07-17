# Image Conversion Test Document (Markdown)

## Case 1: standalone image in its own paragraph

Paragraph before the image.

![standalone logo](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png)

Paragraph after the image.

## Case 2: inline image inside running text

Text before ![inline logo](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png) text after, same paragraph.

## Case 3: two consecutive images with no separating text

![first](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png)![second](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png)

## Case 4: image wrapped in a link

[![linked logo](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png)](https://example.com)

## Case 5: image inside a list item

- List item with an image ![bullet logo](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png) inline
- Plain list item, no image

## Case 6: image inside a table cell

| Description | Image |
|---|---|
| Logo in a cell | ![cell logo](https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png) |

## Case 7: reference-style image syntax

Reference-style: ![ref logo][logoref]

[logoref]: https://www.gstatic.com/images/branding/googlelogo/1x/googlelogo_color_92x30dp.png "Google logo"

## Case 8: image with an unreachable URL (parser-level drop, not a fetch failure)

![unreachable image](https://does-not-exist.invalid/nope.png)

Final paragraph, confirms the document is not truncated after all image cases.
