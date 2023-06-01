# Copyright (C) 2020  Davis Remmel
# Copyright 2021 Robert Schroll
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import gc
import json
import logging

from reportlab.graphics import renderPDF
from rmscene import read_blocks, SceneLineItemBlock, TreeNodeBlock
from rmscene.scene_items import Pen, PenColor, Point
from svglib.svglib import svg2rlg

from . import lines, pens
# use for v4 and v5
from .lines import Layer, Segment, Stroke
from .constants import DISPLAY, PDFHEIGHT, PDFWIDTH, PTPERPX, TEMPLATE_PATH
from .pens.highlighter import HighlighterPen

log = logging.getLogger(__name__)

class DocumentPage:
    # A single page in a document
    def __init__(self, source, pid, pagenum, template_name = None):
        # Page 0 is the first page!
        self.source = source
        self.num = pagenum

        pidhighlights = pid

        # On disk, these files are named by a UUID
        self.rmpath = f'{{ID}}/{pid}.rm'
        if not source.exists(self.rmpath):
            # From the API, these files are just numbered, however the
            # json file for the highlights still uses the UUID-style pid.
            pid = str(pagenum)
            self.rmpath = f'{{ID}}/{pid}.rm'

        with self.source.open(self.rmpath, 'rb') as f:
            self.version = lines.getVersion(f)

        # Try to load page metadata
        self.metadict = None
        metafilepath = f'{{ID}}/{pid}-metadata.json'
        if source.exists(metafilepath):
            with source.open(metafilepath, 'r') as f:
                self.metadict = json.load(f)

        # Try to load smart highlights
        self.highlightdict = None
        highlightfilepath = f'{{ID}}.highlights/{pidhighlights}.json'
        if source.exists(highlightfilepath):
            with source.open(highlightfilepath, 'r') as f:
                self.highlightdict = json.load(f)

        # Try to load template
        self.template = None
        # v4 and v5
        ver = self.version
        if ver == 6:
            template_path = TEMPLATE_PATH / f'{template_name}.svg'
            if template_name != 'Blank' and template_path.exists():
                self.template = str(template_path)
        else:
            template_names = []
            pagedatapath = '{ID}.pagedata'
            if source.exists(pagedatapath):
                with source.open(pagedatapath, 'r') as f:
                    template_names = f.read().splitlines()

            if template_names:
                # I have encountered an issue with some PDF files, where the
                # rM won't save the page template for later pages. In this
                # case, just take the last-available page template, which
                # is usually 'Blank'.
                try:
                    template_name = template_names[self.num] # pages with different templates
                except IndexError:
                    template_name = template_name = [min(self.num, len(template_names) - 1)]

                template_path = TEMPLATE_PATH / f'{template_name}.svg'
                if template_name != "Blank" and template_path.exists():
                    self.template = str(template_path)

        # Load layers
        self.layers = []
        self.load_layers()

    def get_grouped_annotations(self):
        # Return the annotations grouped by proximity. If they are
        # within a distance of each other, count them as a single
        # annotation.

        # Annotations should be delivered in an array, where each
        # index is a tuple (LayerName,
        annotations = []
        for layer in self.layers:
            annotations.append(layer.get_grouped_annotations())
        return annotations

    # v6
    def get_layers(self, source):
        blocks = read_blocks(source)

        def to_segment(point: Point) -> Segment:
            # TODO how to get the correct transformations?
            return Segment(
                x=point.x * 0.7 + 1404 / 2.0 - 40,
                y=point.y * 0.7, # - 1872 / 14.0,
                speed=point.speed,
                direction=point.direction,
                width=point.width / 4.0,
                pressure=point.pressure,
            )

        layers = []
        current_layer = ""
        current_strokes = []

        for block in blocks:
            if isinstance(block, SceneLineItemBlock):
                # import pprint
                # print("block:")
                # pprint.pprint(block)
                # TODO this seems wrong!
                block = block.item
                if block.value is None:
                    continue

                color: PenColor = block.value.color
                tool: Pen = block.value.tool
                points: list[Point] = block.value.points
                thickness_scale: float = block.value.thickness_scale
                # starting_length: float = block.value.starting_length

                segments = list(map(to_segment, points))
                stroke = Stroke(tool, color, None, thickness_scale, None, segments)
                current_strokes.append(stroke)

            elif isinstance(block, TreeNodeBlock):
                if current_layer == block.group.label.value:
                    continue

                layers.append(Layer(current_strokes, current_layer))
                current_layer = block.group.label.value
                current_strokes = []
            else:
                print(f'warning: not converting block: {block.__class__}')

        layers.append(Layer(current_strokes, current_layer))
        current_strokes = []

        return layers[1:]

    def load_layers(self):
        # Loads layers from the .rm files

        if not self.source.exists(self.rmpath):
            # no layers, obv
            return

        # Load reMy version of page layers
        pagelayers = None
        with self.source.open(self.rmpath, 'rb') as f:
            ver = self.version
            if ver == 6:
                pagelayers = self.get_layers(f)
            else:
                # handles unsupported versions
                _, pagelayers = lines.readLines(f)

        # Load page layers of highlights
        if self.highlightdict:
            _, pagelayershlght = lines.readHighlights(self.highlightdict)
            
            from operator import add
            pagelayers = list(map(add, pagelayers, pagelayershlght))

        # Load layer data
        for i in range(0, len(pagelayers)):
            if ver == 6:
                layerstrokes, layer_name = pagelayers[i]
            else:
                layerstrokes = pagelayers[i]
                try:
                    layer_name = self.metadict['layers'][i]['name']
                except:
                    layer_name = 'Layer ' + str(i+1)

            layer = DocumentPageLayer(self, name=layer_name)
            layer.strokes = layerstrokes
            self.layers.append(layer)

    def render_to_painter(self, canvas, vector, template_alpha):
        # Render template layer
        if self.template:
            if template_alpha > 0:
                background = svg2rlg(self.template)
                background.scale(PDFWIDTH / background.width, PDFWIDTH / background.width)
                renderPDF.draw(background, canvas, 0, 0)
                if template_alpha < 1:
                    canvas.saveState()
                    canvas.setFillColorRGB(1., 1., 1.)
                    canvas.setFillAlpha(1 - template_alpha)
                    canvas.rect(0, 0, PDFWIDTH, PDFHEIGHT, fill=True, stroke=False)
                    canvas.restoreState()
            # Bitmaps are rendered into the PDF as XObjects, which are
            # easy to pick out for layers. Vectors will render
            # everything inline, and so we need to add a 'magic point'
            # to mark the end of the template layer.
            if False and vector:  #TODO
                pen = GenericPen(color=Qt.transparent, vector=vector)
                painter.setPen(pen)
                painter.drawPoint(800, 85)

        # The annotation coordinate system is upside down compared to the PDF
        # coordinate system, so offset the bottom to the top and then flip
        # vertically along the old bottom / new top to place the annotations
        # correctly.
        canvas.translate(0, PDFHEIGHT)
        canvas.scale(PTPERPX, -PTPERPX)
        # Render user layers
        for layer in self.layers:
            # Bitmaps are rendered into the PDF as XObjects, which are
            # easy to pick out for layers. Vectors will render
            # everything inline, and so we need to add a 'magic point'
            # to mark the beginning of layers.
            if False and vector:  #TODO
                pen = GenericPen(color=Qt.transparent, vector=vector)
                painter.setPen(pen)
                painter.drawPoint(420, 69)
            layer.render_to_painter(canvas, vector)
        canvas.showPage()


class DocumentPageLayer:
    pen_widths = []

    def __init__(self, page, name=None):
        self.page = page
        self.name = name

        # pen colors
        self.colors = [
            # Colors described as: name on rM (rendered color)
            (56/255, 57/255, 56/255),    # black (very dark grey)
            (0.5, 0.5, 0.5),             # grey  (light grey)
            (1, 1, 1),                   # white (white)
            (1, 1, 0),
            (0, 1, 0),
            (1, 0, 1),
            (52/255, 120/255, 247/255),  # blue  (unnoticeably pastel blue)
            (228/255, 95/255, 89/255)    # red   (slightly pinkish red)
        ]
        
        # highlight colors
        self.highlight_colors = [
            # Colors described as: name on rM (rendered color)
            (None, None, None),
            (248/255, 241/255, 36/255),  # yellow (yellow)
            (None, None, None),
            (248/255, 241/255, 36/255),  # yellow (yellow)
            (183/255, 248/255, 73/255),  # green  (yellowish green)
            (248/255, 79/255, 145/255)   # pink   (reddish pink)
        ]

        # Set this from the calling func
        self.strokes = None

        # Store PDF annotations with the layer, in case actual
        # PDF layers are ever implemented.
        self.annot_paths = []

    def get_grouped_annotations(self):
        # return: (LayerName, [(AnnotType, minX, minY, maxX, maxY)])

        # Compare all the annot_paths to each other. If any overlap,
        # they will be grouped together. This is done recursively.
        def grouping_func(pathset):
            newset = []

            for p in pathset:
                annotype = p[0]
                path = p[1]
                did_fit = False
                for i, g in enumerate(newset):
                    gannotype = g[0]
                    group = g[1]
                    # Only compare annotations of the same type
                    if gannotype != annotype:
                        continue
                    if path.intersects(group):
                        did_fit = True
                        newset[i] = (annotype, group.united(path))
                        break
                if did_fit:
                    continue
                # Didn't fit, so place into a new group
                newset.append(p)

            if len(newset) != len(pathset):
                # Might have stuff left to group
                return grouping_func(newset)
            else:
                # Nothing was grouped, so done
                return newset

        grouped = grouping_func(self.annot_paths)

        # Get the bounding rect of each group, which sets the PDF
        # annotation geometry.
        annot_rects = []
        for p in grouped:
            annotype = p[0]
            path = p[1]
            rect = path.boundingRect()
            annot = (annotype,
                     float(rect.x()),
                     float(rect.y()),
                     float(rect.x() + rect.width()),
                     float(rect.y() + rect.height()))
            annot_rects.append(annot)

        return (self.name, annot_rects)

    def paint_strokes(self, canvas, vector):
        for stroke in self.strokes:
            pen, color, unk1, width, unk2, segments = stroke

            penclass = pens.PEN_MAPPING.get(pen)
            if penclass is None:
                log.error("Unknown pen code %d" % pen)
                penclass = pens.GenericPen

            # if pen is highlighter
            elif penclass == HighlighterPen:
                pencolor = self.highlight_colors[color]
            # if pen is not highlighter
            else:
                pencolor = self.colors[color]

            qpen = penclass(vector=vector,
                            layer=self,
                            color=pencolor)

            # Do the needful
            qpen.paint_stroke(canvas, stroke)

    def render_to_painter(self, painter, vector):
        if vector: # Turn this on with vector otherwise off to get hybrid
            self.paint_strokes(painter, vector=vector)
            return

        assert False

        # I was having problems with QImage corruption (garbage data)
        # and memory leaking on large notebooks. I fixed this by giving
        # the QImage a reference array to pre-allocate RAM, then reset
        # the reference count after I'm done with it, so that it gets
        # cleaned up by the python garbage collector.

        devpx = DISPLAY['screenwidth'] \
            * DISPLAY['screenheight']
        bytepp = 4  # ARGB32
        qimage = QImage(b'\0' * devpx * bytepp,
                        DISPLAY['screenwidth'],
                        DISPLAY['screenheight'],
                        QImage.Format_ARGB32)

        imgpainter = QPainter(qimage)
        imgpainter.setRenderHint(QPainter.Antialiasing)
        #imgpainter.setRenderHint(QPainter.LosslessImageRendering)
        self.paint_strokes(imgpainter, vector=vector)
        imgpainter.end()

        painter.drawImage(0, 0, qimage)

        del imgpainter
        del qimage
        gc.collect()
