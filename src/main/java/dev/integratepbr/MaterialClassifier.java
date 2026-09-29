package dev.integratepbr;

import java.awt.image.BufferedImage;
import java.util.Locale;

/** Conservative name and image-feature classifier. Uncertain textures stay neutral. */
public final class MaterialClassifier {
    private MaterialClassifier() {}

    public static MaterialType classify(BufferedImage image, String name) {
        return assess(image, name).material();
    }

    /** An automatic choice may still need human review; it is never silently treated as certain. */
    public record Decision(MaterialType material, String reviewReason) {
        public boolean uncertain() { return reviewReason != null; }
    }

    public static Decision assess(BufferedImage image, String name) {
        return assess(image, name, null, null, null, false);
    }

    public static Decision assess(BufferedImage image, String name, String learnedMetalTerm,
                                  String learnedWoodTerm, String learnedStoneTerm, boolean durableAttacker) {
        String words = "_" + name.toLowerCase(Locale.ROOT).replaceAll("[^a-z0-9]+", "_") + "_";
        Features pixels = Features.read(image);
        if (has(words, "cloth", "fabric", "wool", "carpet", "canvas", "linen", "cotton")) return sure(MaterialType.FABRIC);
        if (has(words, "leather", "hide", "pelt")) return sure(MaterialType.LEATHER);
        boolean equipment = has(words, "sword", "axe", "pickaxe", "shovel", "hoe", "helmet",
                "chestplate", "leggings", "boots", "ingot", "nugget", "armor", "layer");
        if (has(words, "smithing", "workbench", "machine")) return sure(MaterialType.WOOD_METAL);
        if (has(words, "ironwood")) return sure(equipment ? MaterialType.METAL : MaterialType.WOOD_METAL);
        if (has(words, "fiery") && (equipment || has(words, "block"))) return sure(MaterialType.METAL);
        if (equipment && has(words, "diamond", "emerald", "ruby", "sapphire", "amethyst",
                "netherite", "electrum", "mythril", "mithril", "adamant", "titanium")) return sure(MaterialType.METAL);
        if (has(words, "knightmetal", "steeleaf")) return sure(MaterialType.METAL);
        if (has(words, "glass", "ice", "crystal")) return sure(MaterialType.GLASS);
        if (has(words, "wood", "plank", "planks", "log", "stem", "bark")) return sure(MaterialType.WOOD);
        if (has(words, "leaf", "leaves")) return sure(MaterialType.LEAVES);
        if (has(words, "ore")) return uncertain(MaterialType.STONE, "ore may mix rock and mineral regions");
        if (has(words, "stone", "rock", "deepslate", "cobble", "cobbled", "cobblestone", "sandstone",
                "brick", "bricks", "stonebrick", "stonebricks", "tile", "tiles")) return sure(MaterialType.STONE);
        if (has(words, "grass", "moss", "flower", "vine", "sapling")) return sure(MaterialType.PLANT);
        if (has(words, "iron", "gold", "copper", "silver", "steel", "metal", "bronze", "aluminum", "aluminium")) return sure(MaterialType.METAL);
        boolean woodenProduct = has(words, "door", "trapdoor", "fence", "gate", "sign", "boat",
                "chest", "button", "pressure", "stairs", "slab", "stick", "ladder", "beam", "panel", "table");
        if (learnedWoodTerm != null && woodenProduct)
            return uncertain(MaterialType.WOOD, "wood inferred from matching sapling: " + learnedWoodTerm);
        boolean masonryProduct = has(words, "stairs", "slab", "wall", "pillar", "tile", "tiles",
                "polished", "chiseled", "carved", "engraved", "block");
        if (learnedStoneTerm != null && masonryProduct)
            return uncertain(MaterialType.STONE, "stone inferred from matching stone family: " + learnedStoneTerm);
        if (durableAttacker && learnedWoodTerm != null)
            return uncertain(MaterialType.WOOD, "wooden weapon inferred from matching sapling: " + learnedWoodTerm);
        if (durableAttacker && learnedStoneTerm != null)
            return uncertain(MaterialType.STONE, "stone weapon inferred from matching stone family: " + learnedStoneTerm);
        if (learnedMetalTerm != null)
            return uncertain(MaterialType.METAL, "metal inferred from ingot/nugget/ore names: " + learnedMetalTerm);
        if (durableAttacker)
            return uncertain(MaterialType.METAL, "durable item with main-hand attack damage; metal reflection inferred");

        // Unknown equipment names are judged from the blade/plate pixels, not only an average RGB.
        // Their automatic result remains in the review list because appearance cannot prove composition.
        if (equipment || has(words, "plate", "blade", "gear")) {
            if (pixels.reflectiveFraction() >= 0.36 || pixels.goldColoredFraction() >= 0.25)
                return uncertain(MaterialType.METAL, "reflective-looking equipment; material inferred from pixels");
            if (pixels.warmBrown())
                return uncertain(MaterialType.WOOD, "warm-looking equipment; material inferred from pixels");
            return uncertain(MaterialType.GENERIC, "equipment material unclear");
        }
        if (has(words, "pane", "window") && pixels.partlyTransparent())
            return uncertain(MaterialType.GLASS, "transparent surface inferred from pixels");
        if (has(words, "pouch", "strap", "harness") && pixels.warmBrown())
            return uncertain(MaterialType.LEATHER, "leather inferred from color");
        if (pixels.partlyTransparent() && pixels.visiblePixels() > 0)
            return uncertain(MaterialType.GLASS, "transparent surface without a material name");
        return uncertain(MaterialType.GENERIC, "no reliable material cue");
    }

    private static Decision sure(MaterialType material) { return new Decision(material, null); }
    private static Decision uncertain(MaterialType material, String reason) { return new Decision(material, reason); }

    private static boolean has(String words, String... terms) {
        for (String term : terms) if (words.contains("_" + term + "_")) return true;
        return false;
    }

    private record Features(int visiblePixels, int partialPixels, int reflectivePixels, int goldColoredPixels, double red, double green,
                            double blue, double saturation, double brightness) {
        static Features read(BufferedImage image) {
            long red = 0, green = 0, blue = 0, saturation = 0, brightness = 0;
            int visible = 0, partial = 0, reflective = 0, goldColored = 0;
            for (int y = 0; y < image.getHeight(); y++) for (int x = 0; x < image.getWidth(); x++) {
                int pixel = image.getRGB(x, y), alpha = pixel >>> 24;
                if (alpha == 0) continue;
                visible++;
                if (alpha < 255) partial++;
                int r = pixel >>> 16 & 255, g = pixel >>> 8 & 255, b = pixel & 255;
                red += r; green += g; blue += b;
                saturation += Math.max(r, Math.max(g, b)) - Math.min(r, Math.min(g, b));
                brightness += (r + g + b) / 3;
                int light = (r + g + b) / 3;
                boolean neutral = Math.max(r, Math.max(g, b)) - Math.min(r, Math.min(g, b)) < 45;
                boolean cool = b >= r + 8 && g >= r + 5;
                if (light >= 72 && (neutral || cool)) reflective++;
                if (r >= 145 && g >= 140 && Math.abs(r - g) < 28 && b < Math.min(r, g) - 45)
                    goldColored++;
            }
            if (visible == 0) return new Features(0, 0, 0, 0, 0, 0, 0, 0, 0);
            return new Features(visible, partial, reflective, goldColored, (double) red / visible, (double) green / visible,
                    (double) blue / visible, (double) saturation / visible, (double) brightness / visible);
        }
        double reflectiveFraction() { return visiblePixels == 0 ? 0 : (double) reflectivePixels / visiblePixels; }
        double goldColoredFraction() { return visiblePixels == 0 ? 0 : (double) goldColoredPixels / visiblePixels; }
        boolean partlyTransparent() { return partialPixels > visiblePixels / 3; }
        boolean warmBrown() { return red > green * 1.08 && green > blue * 1.08 && brightness > 35 && brightness < 190; }
    }
}
