package dev.integratepbr.texture;

import java.awt.image.BufferedImage;

/** Conservative labPBR maps with region materials and structure-aware block relief. */
public final class LabPbrMaps {
    private static final int FULL_DEPTH_RELIEF = 48;
    private LabPbrMaps() {}

    public record Pair(BufferedImage normal, BufferedImage specular) {}

    public static Pair generate(BufferedImage source, MaterialType material, String name, boolean blockTexture,
                         double[][] depthOverride) {
        int width = source.getWidth(), height = source.getHeight();
        if (width < 1 || height < 1) throw new IllegalArgumentException("Empty texture");
        MaterialType[][] regions = MaterialRegions.classify(source, material, name);
        double metalDark = 255, metalLight = 0;
        if (!blockTexture) for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            if (regions[y][x] != MaterialType.METAL || (source.getRGB(x, y) >>> 24) < 128) continue;
            double light = luminance(source.getRGB(x, y));
            metalDark = Math.min(metalDark, light);
            metalLight = Math.max(metalLight, light);
        }
        double[][] depth = depthOverride != null ? depthOverride : blockTexture ? TextureStructure.depth(source, name, true)
                : ItemStructure.depth(source, regions);
        BufferedImage normal = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
        BufferedImage specular = new BufferedImage(width, height, BufferedImage.TYPE_INT_ARGB);
        int frameHeight = !blockTexture && height > width && height % width == 0 ? width : height;
        int noSurface = rgba(0, 0, 0, 255);
        boolean strippedLog = blockTexture && TextureStructure.has(name,"stripped")
                && TextureStructure.has(name,"log","stem","bark");
        boolean shallow = blockTexture && TextureStructure.has(name,"stripped","door","trapdoor");
        // Ordinary log end grain keeps its deeper 48-unit relief. Stripped log
        // ends are much flatter (8 units); doors and trapdoors keep their 24-unit cap.
        int depthStrength = !blockTexture ? 30 : strippedLog ? 8 : shallow ? 24 : FULL_DEPTH_RELIEF;
        // Fine surface normals remain legible without deep parallax displacement.
        int normalStrength = strippedLog ? 18 : shallow ? 36 : depthStrength;
        for (int y = 0; y < height; y++) for (int x = 0; x < width; x++) {
            double relief = depth[y][x];
            int frameStart = y / frameHeight * frameHeight;
            int above = blockTexture ? Math.floorMod(y-1,height) : Math.max(frameStart,y-1);
            int below = blockTexture ? (y+1)%height : Math.min(frameStart+frameHeight-1,y+1);
            int lx = blockTexture ? Math.floorMod(x-1,width) : Math.max(0,x-1);
            int rx = blockTexture ? (x+1)%width : Math.min(width-1,x+1);
            double left = depth[y][lx], right = depth[y][rx];
            double up = depth[above][x], down = depth[below][x];
            // labPBR alpha is height; depth has the opposite sign. Scale by texel size,
            // then normalize the tangent normal instead of clipping its components independently.
            double slopeScale = normalStrength / 255.0 * .25 * width * .5;
            // Enhanced relief has explicit bevel texels. Do not extend their slope
            // onto adjacent plateaus or across a sharp tonal step. Use encoded
            // heights so sub-byte relief cannot create normals on a flat height map.
            double dx = right-left, dy = down-up;
            if (blockTexture && depthOverride != null) {
                double center = clamp(relief*depthStrength);
                dx = limitedSlope(clamp(left*depthStrength), center,
                        clamp(right*depthStrength))/depthStrength;
                dy = limitedSlope(clamp(up*depthStrength), center,
                        clamp(down*depthStrength))/depthStrength;
            }
            double sx = dx*slopeScale, sy = dy*slopeScale;
            double length = Math.sqrt(1+sx*sx+sy*sy);
            double nx = 127*sx/length, ny = 127*sy/length;
            int sourcePixel = source.getRGB(x, y);
            MaterialType region = regions[y][x];
            if (!blockTexture && region == MaterialType.METAL && (sourcePixel >>> 24) >= 128) {
                nx += (opacity(source, x - 1, y) - opacity(source, x + 1, y)) * 36;
                double upOpacity = y % frameHeight == 0 ? 0 : opacity(source, x, y - 1);
                double downOpacity = (y + 1) % frameHeight == 0 ? 0 : opacity(source, x, y + 1);
                ny += (upOpacity - downOpacity) * 36;
                nx += (brightness(source, x - 1, y) - brightness(source, x + 1, y)) * 12;
                double upBrightness = y % frameHeight == 0 ? 0 : brightness(source, x, y - 1);
                double downBrightness = (y + 1) % frameHeight == 0 ? 0 : brightness(source, x, y + 1);
                ny += (upBrightness - downBrightness) * 12;
            }
            int red = clamp(128 + nx);
            int green = clamp(128 + ny);
            int occlusion = clamp(255 - relief * (strippedLog ? 2 : shallow ? 6 : 12));
            int heightMap = clamp(255 - relief * depthStrength);
            if ((sourcePixel >>> 24) == 0) {
                normal.setRGB(x, y, rgba(128, 128, 255, 255));
                specular.setRGB(x, y, noSurface);
            } else {
                normal.setRGB(x, y, rgba(red, green, occlusion, heightMap));
                int smoothness = region.smoothness();
                if (blockTexture && region == MaterialType.WOOD) {
                    boolean log = TextureStructure.has(name,"log","stem","bark");
                    boolean end = TextureStructure.has(name,"top","end");
                    boolean stripped = TextureStructure.has(name,"stripped");
                    int woodSmoothness = stripped ? (end ? 136 : 162)
                            : log ? (end ? 126 : 87) : 148;
                    smoothness = clamp(woodSmoothness - relief*(stripped ? 8 : 30));
                } else if (blockTexture && region == MaterialType.STONE
                        && TextureStructure.has(name,"brick","bricks","tile","tiles")) {
                    smoothness = clamp(123-relief*45);
                }
                if (!blockTexture && region == MaterialType.METAL) {
                    double span = Math.max(32, metalLight - metalDark);
                    smoothness = clamp(130 + Math.max(0, Math.min(1,
                            (luminance(sourcePixel) - metalDark) / span)) * 90);
                }
                specular.setRGB(x, y, rgba(smoothness, region.f0(), region.porosity(), 255));
            }
        }
        return new Pair(normal, specular);
    }

    private static double limitedSlope(double before, double center, double after) {
        double a = center-before, b = after-center;
        if (a*b <= 0) return 0;
        return 2*Math.copySign(Math.min(Math.abs(a),Math.abs(b)),a);
    }

    private static int rgba(int red, int green, int blue, int alpha) {
        return alpha << 24 | red << 16 | green << 8 | blue;
    }

    private static double opacity(BufferedImage image, int x, int y) {
        if (x < 0 || y < 0 || x >= image.getWidth() || y >= image.getHeight()) return 0;
        return (image.getRGB(x, y) >>> 24) / 255.0;
    }

    private static double brightness(BufferedImage image, int x, int y) {
        if (x < 0 || y < 0 || x >= image.getWidth() || y >= image.getHeight()) return 0;
        int pixel = image.getRGB(x, y);
        return (pixel >>> 24) == 0 ? 0 : luminance(pixel) / 255.0;
    }

    private static double luminance(int pixel) {
        return (pixel >>> 16 & 255) * 0.2126 + (pixel >>> 8 & 255) * 0.7152
                + (pixel & 255) * 0.0722;
    }

    private static int clamp(double value) { return (int) Math.round(Math.max(0, Math.min(255, value))); }
}
