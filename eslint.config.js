export default [
    {
        files: ["frontend/js/**/*.js"],
        languageOptions: {
            ecmaVersion: 2022,
            sourceType: "script"
        },
        rules: {
            "no-unused-vars": "off",
            "no-undef": "off"
        }
    }
];
