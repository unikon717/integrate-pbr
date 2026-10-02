package dev.integratepbr.pack;

import net.minecraft.resources.ResourceLocation;

import javax.imageio.ImageIO;
import java.awt.image.BufferedImage;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.Properties;

/** File storage for the owned generated pack; classification and reloads stay outside. */
final class GeneratedPackStore {
    private GeneratedPackStore() {}

    static Properties open(Path root, Path marker) throws IOException {
        if (Files.exists(root) && !Files.isRegularFile(marker)) {
            throw new IOException("Refusing to modify an existing pack without our ownership marker: " + root);
        }
        Files.createDirectories(root);
        Properties cache = new Properties();
        if (Files.isRegularFile(marker)) {
            try (var input = Files.newInputStream(marker)) { cache.load(input); }
            if (!"IntegratePBR".equals(cache.getProperty("generator"))) {
                throw new IOException("Invalid generated pack ownership marker: " + marker);
            }
        }
        boolean fresh = !Files.isRegularFile(marker);
        if (fresh) {
            cache.setProperty("generator", "IntegratePBR");
            saveCache(cache, marker);
        }
        return cache;
    }

    static void discard(Path albedo, Path normal, Path specular, Properties cache, String key, String reviewKey) throws IOException {
        deleteMap(albedo);
        deleteMap(normal);
        deleteMap(specular);
        cache.remove(key);
        cache.remove(reviewKey);
    }

    static Path sidecar(Path png) { return png.resolveSibling(png.getFileName() + ".mcmeta"); }

    static void deleteMap(Path png) throws IOException {
        Files.deleteIfExists(png);
        Files.deleteIfExists(sidecar(png));
    }

    static ResourceLocation companion(ResourceLocation base, String suffix) {
        String path = base.getPath();
        return ResourceLocation.fromNamespaceAndPath(base.getNamespace(),
                path.substring(0, path.length() - 4) + suffix + ".png");
    }

    static Path output(Path root, ResourceLocation location) throws IOException {
        Path result = root.resolve("assets").resolve(location.getNamespace()).resolve(location.getPath()).normalize();
        if (!result.startsWith(root)) throw new IOException("Invalid resource path: " + location);
        return result;
    }

    static void writePng(BufferedImage image, Path target) throws IOException {
        Files.createDirectories(target.getParent());
        Path temporary = Files.createTempFile(target.getParent(), "integratepbr-", ".tmp");
        try {
            if (!ImageIO.write(image, "PNG", temporary.toFile())) throw new IOException("PNG writer unavailable");
            replace(temporary, target);
        } finally { Files.deleteIfExists(temporary); }
    }

    static void writeMap(BufferedImage image, byte[] metadata, Path target) throws IOException {
        writePng(image, target);
        if (metadata == null) {
            Files.deleteIfExists(sidecar(target));
            return;
        }
        Path companion = sidecar(target);
        Path temporary = Files.createTempFile(target.getParent(), "integratepbr-meta-", ".tmp");
        try {
            Files.write(temporary, metadata);
            replace(temporary, companion);
        } finally { Files.deleteIfExists(temporary); }
    }

    static void saveCache(Properties cache, Path target) throws IOException {
        Path temporary = Files.createTempFile(target.getParent(), "integratepbr-cache-", ".tmp");
        try {
            try (var output = Files.newOutputStream(temporary)) { cache.store(output, "Generated pack cache"); }
            replace(temporary, target);
        } finally { Files.deleteIfExists(temporary); }
    }

    private static void replace(Path from, Path to) throws IOException {
        try { Files.move(from, to, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
        catch (java.nio.file.AtomicMoveNotSupportedException error) {
            Files.move(from, to, StandardCopyOption.REPLACE_EXISTING);
        }
    }
}
