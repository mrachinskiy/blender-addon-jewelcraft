# ##### BEGIN GPL LICENSE BLOCK #####
#
#  JewelCraft jewelry design toolkit for Blender.
#  Copyright (C) 2015-2019  Mikhail Rachinskiy
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <https://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####


from functools import lru_cache
from math import sin, cos, tau

import bpy
from bpy_extras.view3d_utils import location_3d_to_region_2d
import bgl
import blf
import gpu
from gpu_extras.batch import batch_for_shader
from mathutils import Matrix, Vector

from .. import var
from . import unit


_handler = None
shader = gpu.shader.from_builtin("3D_UNIFORM_COLOR")

_handler_font = None
_font_loc = []
shader_2d = gpu.shader.from_builtin('2D_UNIFORM_COLOR')


def handler_add(self, context):
    global _handler
    global _handler_font

    if _handler is None:
        _handler = bpy.types.SpaceView3D.draw_handler_add(draw, (self, context), "WINDOW", "POST_VIEW")
        _handler_font = bpy.types.SpaceView3D.draw_handler_add(draw_font, (self, context), "WINDOW", "POST_PIXEL")


def handler_del():
    global _handler
    global _handler_font

    if _handler is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_handler, "WINDOW")
        bpy.types.SpaceView3D.draw_handler_remove(_handler_font, "WINDOW")
        _handler = None
        _handler_font = None


def handler_toggle(self, context):

    if context.area.type == "VIEW_3D":

        if self.widget_toggle:
            handler_add(self, context)
        else:
            handler_del()

        context.area.tag_redraw()


@lru_cache(maxsize=128)
def circle_coords(radius):
    coords = []
    angle = tau / 64

    for i in range(64):
        x = sin(i * angle) * radius
        y = cos(i * angle) * radius
        coords.append(Vector((x, y, 0.0)))

    return coords


def draw(self, context):
    if (
        not context.window_manager.jewelcraft.widget_toggle or
        not context.space_data.overlay.show_overlays
    ):
        return

    global _font_loc

    prefs = context.preferences.addons[var.ADDON_ID].preferences
    show_all = prefs.widget_show_all
    use_ovrd = prefs.widget_use_overrides
    is_df = context.mode == "EDIT_MESH" and context.edit_object.is_instancer
    default_color = prefs.widget_color
    default_linewidth = prefs.widget_linewidth
    default_spacing = prefs.widget_spacing

    if is_df:
        df = context.edit_object

        for ob_act in df.children:
            if "gem" in ob_act:
                is_act_gem = True
                break
        else:
            is_act_gem = False
            if not show_all:
                return

        if is_act_gem:
            df.update_from_editmode()
            polys = df.data.polygons
            ob_act_loc = df.matrix_world @ polys[polys.active].center
            ob_act_rad = max(ob_act.dimensions[:2]) / 2
            df_pass = False

    else:
        ob_act = context.object
        is_act_gem = "gem" in ob_act if ob_act else False

        if not (show_all or is_act_gem):
            return

        if is_act_gem:
            ob_act_loc = ob_act.matrix_world.translation
            ob_act_rad = max(ob_act.dimensions[:2]) / 2

    if is_act_gem:
        if use_ovrd and "jewelcraft_widget" in ob_act:
            ob_act_spacing = ob_act["jewelcraft_widget"].get("spacing", default_spacing)
        else:
            ob_act_spacing = default_spacing

        _from_scene = unit.Scale().from_scene

    shader.bind()
    bgl.glEnable(bgl.GL_BLEND)
    bgl.glEnable(bgl.GL_LINE_SMOOTH)
    bgl.glDepthMask(bgl.GL_FALSE)
    bgl.glPointSize(5.0)

    if prefs.widget_show_in_front:
        bgl.glDisable(bgl.GL_DEPTH_TEST)

    for dup in context.depsgraph.object_instances:

        if dup.is_instance:
            ob = dup.instance_object.original
        else:
            ob = dup.object.original

        if "gem" not in ob:
            continue

        ob_rad = max(ob.dimensions[:2]) / 2
        ob_loc = dup.matrix_world.translation

        if is_act_gem:
            dis_ob = (ob_act_loc - ob_loc).length
            dis_gap = _from_scene(dis_ob - (ob_act_rad + ob_rad))
            dis_thold = dis_gap < 0.8

            if not (show_all or dis_thold):
                continue

            if is_df:
                if df_pass:
                    is_act = False
                else:
                    df_pass = is_act = dup.matrix_world.translation == ob_act_loc
            else:
                is_act = ob is ob_act

        if use_ovrd and "jewelcraft_widget" in ob:
            _color = ob["jewelcraft_widget"].get("color", default_color)
            _linewidth = ob["jewelcraft_widget"].get("linewidth", default_linewidth)
            _spacing = ob["jewelcraft_widget"].get("spacing", default_spacing)
        else:
            _color = default_color
            _linewidth = default_linewidth
            _spacing = default_spacing

        bgl.glLineWidth(_linewidth)
        shader.uniform_float("color", _color)

        if is_act_gem and not is_act and dis_thold:

            if dis_ob:
                start = ob_act_loc.lerp(ob_loc, ob_act_rad / dis_ob)
                end = ob_loc.lerp(ob_act_loc, ob_rad / dis_ob)
                mid = start.lerp(end, 0.5)
            else:
                start = ob_loc.copy()
                end = ob_loc.copy()
                mid = ob_loc.copy()

            _font_loc.append((dis_gap, mid, _from_scene(max(ob_act_spacing, _spacing))))

            batch = batch_for_shader(shader, "LINES", {"pos": (start, end)})
            batch.draw(shader)

            batch = batch_for_shader(shader, "POINTS", {"pos": (start, end)})
            batch.draw(shader)

        if show_all or (not is_act and dis_gap < 0.5):

            if dup.is_instance:
                mat = dup.matrix_world
            else:
                mat_loc = Matrix.Translation(ob_loc)
                mat_rot = dup.matrix_world.to_quaternion().to_matrix().to_4x4()
                mat = mat_loc @ mat_rot

            radius = ob_rad + _spacing
            coords = [mat @ co for co in circle_coords(radius)]
            batch = batch_for_shader(shader, "LINE_LOOP", {"pos": coords})
            batch.draw(shader)

    # Restore OpenGL defaults
    # ----------------------------

    bgl.glDisable(bgl.GL_BLEND)
    bgl.glDisable(bgl.GL_LINE_SMOOTH)
    bgl.glDepthMask(bgl.GL_TRUE)
    bgl.glEnable(bgl.GL_DEPTH_TEST)
    bgl.glLineWidth(1.0)
    bgl.glPointSize(1.0)


def draw_font(self, context):
    global _font_loc

    if not _font_loc:
        return

    region = context.region
    region_3d = context.space_data.region_3d
    prefs = context.preferences.addons[var.ADDON_ID].preferences
    font_size = prefs.widget_font_size
    fontid = 0
    blf.size(fontid, font_size, 72)
    blf.color(fontid, 1, 1, 1, 1)

    for dis, loc, spacing in _font_loc:
        bgl.glEnable(bgl.GL_BLEND)
        shader_2d.bind()

        if dis < 0.1:
            color = (0.9, 0.0, 0.0, 1.0)
        elif dis < spacing:
            color = (0.9, 0.7, 0.0, 1.0)
        else:
            color = (0.0, 0.0, 0.0, 0.2)

        dis_str = f"{dis:.2f}"
        dim_x, dim_y = blf.dimensions(fontid, dis_str)
        loc_x, loc_y = location_3d_to_region_2d(region, region_3d, loc)

        verts = (
            (loc_x - 3,         loc_y - 4),
            (loc_x + 3 + dim_x, loc_y - 4),
            (loc_x + 3 + dim_x, loc_y + 4 + dim_y),
            (loc_x - 3,         loc_y + 4 + dim_y),
        )

        shader_2d.uniform_float("color", color)
        batch_font = batch_for_shader(shader_2d, "TRI_FAN", {"pos": verts})
        batch_font.draw(shader_2d)

        blf.position(fontid, loc_x, loc_y, 0)
        blf.draw(fontid, dis_str)

    _font_loc.clear()

    # Restore OpenGL defaults
    # ----------------------------

    bgl.glDisable(bgl.GL_BLEND)
