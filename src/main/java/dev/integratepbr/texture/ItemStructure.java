package dev.integratepbr.texture;

import java.awt.image.BufferedImage;

/** Recesses only metal bevels and coherent internal seams, keeping empty sprite pixels flat. */
final class ItemStructure {
    private ItemStructure() {}

    static double[][] depth(BufferedImage source, MaterialType[][] regions) {
        int width = source.getWidth(), height = source.getHeight();
        int frameHeight = height > width && height % width == 0 ? width : height;
        boolean[][] metal = new boolean[height][width];
        boolean[][] interior = new boolean[height][width];
        boolean[][] core = new boolean[height][width];
        double[][] luminance = new double[height][width];
        double[][] contrast = new double[height][width];
        double[][] depth = new double[height][width];
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            int pixel = source.getRGB(x, y);
            metal[y][x] = (pixel >>> 24) >= 128 && regions[y][x] == MaterialType.METAL;
            luminance[y][x] = (pixel >>> 16 & 255) * 0.2126
                    + (pixel >>> 8 & 255) * 0.7152 + (pixel & 255) * 0.0722;
        }
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            if (!metal[y][x]) continue;
            interior[y][x] = surrounded(metal, x, y, frameHeight);
        }
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            if (!interior[y][x]) continue;
            core[y][x] = surrounded(interior, x, y, frameHeight);
            double neighbor = 0;
            int count = 0;
            for (int[] offset : CARDINAL) {
                int nx = x + offset[0], ny = y + offset[1];
                if (!inFrame(metal, nx, ny, y, frameHeight) || !metal[ny][nx]) continue;
                neighbor += luminance[ny][nx];
                count++;
            }
            if (count >= 3) contrast[y][x] = Math.max(0,
                    Math.min(1, (neighbor / count - luminance[y][x] - 14) / 35));
        }
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            if (!metal[y][x]) continue;
            // A shallow inset bevel is allowed only where the sprite has an interior.
            if (interior[y][x] && !core[y][x]) depth[y][x] = 0.14;
            else if (!interior[y][x] && adjacent(interior, x, y, frameHeight)) depth[y][x] = 0.08;
            if (!interior[y][x] || contrast[y][x] < 0.25) continue;
            if (adjacentContrast(contrast, x, y, frameHeight) >= 0.20)
                depth[y][x] = Math.max(depth[y][x], contrast[y][x] * 0.72);
        }
        return depth;
    }

    private static final int[][] CARDINAL = {{-1, 0}, {1, 0}, {0, -1}, {0, 1}};

    private static boolean surrounded(boolean[][] mask, int x, int y, int frameHeight) {
        for (int dy = -1; dy <= 1; dy++) for (int dx = -1; dx <= 1; dx++) {
            int nx = x + dx, ny = y + dy;
            if (!inFrame(mask, nx, ny, y, frameHeight) || !mask[ny][nx]) return false;
        }
        return true;
    }

    private static boolean adjacent(boolean[][] mask, int x, int y, int frameHeight) {
        for (int[] offset : CARDINAL) {
            int nx = x + offset[0], ny = y + offset[1];
            if (inFrame(mask, nx, ny, y, frameHeight) && mask[ny][nx]) return true;
        }
        return false;
    }

    private static double adjacentContrast(double[][] values, int x, int y, int frameHeight) {
        double maximum = 0;
        for (int[] offset : CARDINAL) {
            int nx = x + offset[0], ny = y + offset[1];
            if (inFrame(values, nx, ny, y, frameHeight)) maximum = Math.max(maximum, values[ny][nx]);
        }
        return maximum;
    }

    private static boolean inFrame(boolean[][] mask, int x, int y, int centerY, int frameHeight) {
        return y >= 0 && y < mask.length && x >= 0 && x < mask[0].length
                && y / frameHeight == centerY / frameHeight;
    }

    private static boolean inFrame(double[][] values, int x, int y, int centerY, int frameHeight) {
        return y >= 0 && y < values.length && x >= 0 && x < values[0].length
                && y / frameHeight == centerY / frameHeight;
    }
}
