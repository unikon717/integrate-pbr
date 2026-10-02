package dev.integratepbr.texture;

import java.awt.image.BufferedImage;
import java.util.ArrayDeque;
import java.util.Locale;

/** Assigns material properties to regions, retaining the base material for uncertain pixels. */
final class MaterialRegions {
    private MaterialRegions() {}

    static MaterialType[][] classify(BufferedImage image, MaterialType base, String name) {
        int width = image.getWidth(), height = image.getHeight();
        MaterialType[][] result = new MaterialType[height][width];
        String words = "_" + name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_") + "_";
        boolean itemTool = words.contains("_sword_") || words.contains("_axe_")
                || words.contains("_pickaxe_") || words.contains("_shovel_");
        boolean woodenDoor = base == MaterialType.WOOD
                && (words.contains("_door_") || words.contains("_trapdoor_"));
        boolean candidate = base == MaterialType.WOOD_METAL
                || itemTool && base == MaterialType.WOOD || woodenDoor;
        int visible = 0, warm = 0, cool = 0, neutralMetal = 0;
        if (candidate) {
            for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
                int pixel = image.getRGB(x, y);
                if ((pixel >>> 24) == 0) continue;
                visible++;
                if (warmWood(pixel)) warm++;
                else if (coolMetal(pixel)) cool++;
                if (neutralMetal(pixel)) neutralMetal++;
            }
        }
        // Wooden doors can contain small metal latches. Require a coherent-sized
        // neutral patch before interpreting gray pixels as metal, to avoid treating
        // isolated pale wood highlights as hardware.
        boolean doorHardware = woodenDoor && visible > 0
                && neutralMetal >= Math.max(3, visible / 512);
        boolean segment = base == MaterialType.WOOD_METAL
                || candidate && visible > 0 && warm * 20 >= visible && warm * 4 <= visible
                && cool * 5 >= visible || doorHardware;
        boolean[][] handles = itemTool && base == MaterialType.METAL
                ? woodHandles(image) : new boolean[height][width];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int pixel = image.getRGB(x, y);
            if (base == MaterialType.STONE && TextureStructure.mossPixel(pixel,name)) result[y][x] = MaterialType.PLANT;
            else if (handles[y][x]) result[y][x] = MaterialType.WOOD;
            else if (!segment || (pixel >>> 24) == 0) result[y][x] = base;
            else if (warmWood(pixel)) result[y][x] = MaterialType.WOOD;
            else if (woodenDoor && doorHardware ? neutralMetal(pixel) : coolMetal(pixel))
                result[y][x] = MaterialType.METAL;
            else result[y][x] = base == MaterialType.WOOD_METAL ? MaterialType.WOOD : base;
        }
        return result;
    }

    /** Selects a coherent warm handle at the lower end of a conventional tool sprite. */
    private static boolean[][] woodHandles(BufferedImage image) {
        int width = image.getWidth(), height = image.getHeight();
        int frameHeight = height > width && height % width == 0 ? width : height;
        boolean[][] warm = new boolean[height][width];
        boolean[][] selected = new boolean[height][width];
        boolean[][] seen = new boolean[height][width];
        for (int start = 0; start < height; start += frameHeight) {
            int end = Math.min(height, start + frameHeight), visible = 0;
            for (int y = start; y < end; y++) for (int x = 0; x < width; x++) {
                int pixel = image.getRGB(x, y);
                if ((pixel >>> 24) == 0) continue;
                visible++;
                warm[y][x] = warmWood(pixel);
            }
            for (int y = start; y < end; y++) for (int x = 0; x < width; x++) {
                if (!warm[y][x] || seen[y][x]) continue;
                ArrayDeque<Integer> queue = new ArrayDeque<>();
                ArrayDeque<Integer> component = new ArrayDeque<>();
                queue.add(y * width + x);
                seen[y][x] = true;
                boolean handleEnd = false;
                while (!queue.isEmpty()) {
                    int index = queue.removeFirst(), px = index % width, py = index / width;
                    component.add(index);
                    if (px < width * 0.45 && py - start >= frameHeight * 0.55) handleEnd = true;
                    for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
                        int nx = px + dx, ny = py + dy;
                        if (nx < 0 || nx >= width || ny < start || ny >= end
                                || !warm[ny][nx] || seen[ny][nx]) continue;
                        seen[ny][nx] = true;
                        queue.add(ny * width + nx);
                    }
                }
                if (handleEnd && component.size() >= 2 && component.size() * 2 <= visible) {
                    for (int index : component) selected[index / width][index % width] = true;
                }
            }
        }
        return selected;
    }

    private static boolean warmWood(int pixel) {
        int red = pixel >>> 16 & 255, green = pixel >>> 8 & 255, blue = pixel & 255;
        return red > green + 8 && green > blue + 2 && red - blue > 20;
    }

    private static boolean coolMetal(int pixel) {
        int red = pixel >>> 16 & 255, green = pixel >>> 8 & 255, blue = pixel & 255;
        int maximum = Math.max(red, Math.max(green, blue));
        int minimum = Math.min(red, Math.min(green, blue));
        return blue > red + 5 && blue > green + 2
                || maximum - minimum < 24 && (red + green + blue) / 3 > 55;
    }

    private static boolean neutralMetal(int pixel) {
        int red = pixel >>> 16 & 255, green = pixel >>> 8 & 255, blue = pixel & 255;
        int maximum = Math.max(red, Math.max(green, blue));
        int minimum = Math.min(red, Math.min(green, blue));
        return maximum - minimum < 24 && (red + green + blue) / 3 > 55;
    }
}
