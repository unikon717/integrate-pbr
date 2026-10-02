package dev.integratepbr.config;

import dev.integratepbr.texture.MaterialType;

import net.minecraft.resources.ResourceLocation;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.HashMap;
import java.util.Map;
import java.util.Properties;

/** Choices keyed by the actual registered item or block ID. Missing means automatic. */
public final class MaterialOverrides {
    public enum Kind { ITEM, BLOCK }
    public record Choice(boolean disabled, MaterialType material) {
        public static Choice disabledChoice() { return new Choice(true, null); }
        public static Choice materialChoice(MaterialType type) { return new Choice(false, type); }
    }

    private final Path file;
    private final Map<String, Choice> choices = new HashMap<>();

    public MaterialOverrides(Path file) throws IOException { this.file = file; load(); }
    public Choice get(Kind kind, ResourceLocation id) { return choices.get(key(kind, id)); }

    public void set(Kind kind, ResourceLocation id, Choice choice) throws IOException {
        String key = key(kind, id);
        Choice previous = choices.put(key, choice);
        try { save(); }
        catch (IOException error) {
            if (previous == null) choices.remove(key); else choices.put(key, previous);
            throw error;
        }
    }

    public void clear(Kind kind, ResourceLocation id) throws IOException {
        String key = key(kind, id);
        Choice previous = choices.remove(key);
        try { save(); }
        catch (IOException error) {
            if (previous != null) choices.put(key, previous);
            throw error;
        }
    }

    private static String key(Kind kind, ResourceLocation id) {
        return kind.name().toLowerCase(java.util.Locale.ROOT) + "." + id;
    }

    private void load() throws IOException {
        if (!Files.isRegularFile(file)) return;
        Properties properties = new Properties();
        try (var input = Files.newInputStream(file)) { properties.load(input); }
        for (String key : properties.stringPropertyNames()) {
            if (!key.matches("(item|block)\\.[a-z0-9_.-]+:[a-z0-9_./-]+")) continue;
            String value = properties.getProperty(key);
            try {
                choices.put(key, value.equalsIgnoreCase("disabled") ? Choice.disabledChoice()
                        : Choice.materialChoice(MaterialType.valueOf(value.toUpperCase(java.util.Locale.ROOT))));
            } catch (IllegalArgumentException ignored) { /* Keep valid entries. */ }
        }
    }

    private void save() throws IOException {
        Files.createDirectories(file.getParent());
        Properties properties = new Properties();
        choices.entrySet().stream().sorted(Map.Entry.comparingByKey()).forEach(entry ->
                properties.setProperty(entry.getKey(), entry.getValue().disabled() ? "disabled"
                        : entry.getValue().material().name().toLowerCase(java.util.Locale.ROOT)));
        Path temporary = Files.createTempFile(file.getParent(), "integratepbr-", ".tmp");
        try {
            try (var output = Files.newOutputStream(temporary)) { properties.store(output, "Integrate PBR material choices"); }
            try { Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.ATOMIC_MOVE); }
            catch (java.nio.file.AtomicMoveNotSupportedException error) {
                Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING);
            }
        } finally { Files.deleteIfExists(temporary); }
    }
}
